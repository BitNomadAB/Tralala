"""Structured RoadMaps: validation, identity reservation, publication and readiness.

The structured plan revision is authoritative. ``loop_phases``, ``loop_plan_items`` and
``loop_dependencies`` are validated projections that carry stable identities; live cards are the
execution projection of the active plan.

``LoopPlanService`` works inside its caller's reader or writer: every method takes the board
repositories of that unit of work, so a plan is registered, published and read in the caller's
transaction. It is the ``PlanViews`` the Loop, Ticket and search services read, and it takes the
clock and the id source as arguments, so every rule here runs in a unit test without a database.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.board import (
    CardsRow,
    LoopDependenciesRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories
from ..repositories.loop_plans import PlannedItem
from ..schemas.loops import PlanPayload, PlanPhase, PlanTicket
from .activity import activity_entry
from .loop_identifiers import format_ticket_key, phase_prefix
from .loops import EXECUTION_STAGES
from .plan_views import (
    BlockedReason,
    Blocker,
    PhaseView,
    PlanView,
    PlanViews,
    Readiness,
    ReadinessItem,
)

# --- the canonical plan --------------------------------------------------------------------------


class CanonicalTicket(TypedDict):
    """A planned Ticket as the plan revision stores it: the model's fields in their declared
    order, then the server-allocated key, sequence and Phase number."""

    id: str
    title: str
    objective: str
    instructions: str
    required_actor: str
    execution_mode: str
    prerequisite_phase_ids: list[str]
    prerequisite_ticket_ids: list[str]
    acceptance_criteria: list[str]
    expected_evidence: list[str]
    human_action_reason: str
    human_instructions: str
    note: str
    priority: str
    key: str
    sequence: int
    phase_number: int


class CanonicalPhase(TypedDict):
    """A Phase as the plan revision stores it: the model's fields in their declared order."""

    id: str
    number: int
    name: str
    objective: str
    entry_conditions: list[str]
    exit_conditions: list[str]
    prerequisite_phase_ids: list[str]
    prerequisite_ticket_ids: list[str]
    narrative: str
    tickets: list[CanonicalTicket]


class CanonicalPlan(TypedDict):
    """The plan revision's payload: the model's structure with the server's keys and numbers."""

    schema_version: int
    summary: str
    loop_id: str
    loop_key: str
    plan_id: str
    revision_number: int
    phases: list[CanonicalPhase]


class PlanDraft(TypedDict):
    plan_id: str
    revision_number: int
    payload: CanonicalPlan


class PublishedTicket(TypedDict):
    id: str
    key: str


class Publication(TypedDict):
    plan_id: str
    tickets: list[PublishedTicket]


# What publishing reads back from a stored payload; any other key is left alone.
class _StoredTicket(TypedDict):
    id: str
    key: str
    title: str
    instructions: str
    priority: str
    required_actor: str
    execution_mode: str
    human_action_reason: str
    human_instructions: str


class _StoredPhase(TypedDict):
    id: str
    tickets: list[_StoredTicket]


class _StoredPlan(TypedDict):
    phases: list[_StoredPhase]


_STORED_PLAN = TypeAdapter(_StoredPlan)


def canonical_ticket(
    ticket: PlanTicket, *, key: str, sequence: int, phase_number: int
) -> CanonicalTicket:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "objective": ticket.objective,
        "instructions": ticket.instructions,
        "required_actor": ticket.required_actor,
        "execution_mode": ticket.execution_mode,
        "prerequisite_phase_ids": list(ticket.prerequisite_phase_ids),
        "prerequisite_ticket_ids": list(ticket.prerequisite_ticket_ids),
        "acceptance_criteria": list(ticket.acceptance_criteria),
        "expected_evidence": list(ticket.expected_evidence),
        "human_action_reason": ticket.human_action_reason,
        "human_instructions": ticket.human_instructions,
        "note": ticket.note,
        "priority": ticket.priority,
        "key": key,
        "sequence": sequence,
        "phase_number": phase_number,
    }


def canonical_phase(phase: PlanPhase, tickets: list[CanonicalTicket]) -> CanonicalPhase:
    return {
        "id": phase.id,
        "number": phase.number,
        "name": phase.name,
        "objective": phase.objective,
        "entry_conditions": list(phase.entry_conditions),
        "exit_conditions": list(phase.exit_conditions),
        "prerequisite_phase_ids": list(phase.prerequisite_phase_ids),
        "prerequisite_ticket_ids": list(phase.prerequisite_ticket_ids),
        "narrative": phase.narrative,
        "tickets": tickets,
    }


def plan_hash(payload: CanonicalPlan) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- validation ----------------------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (TypeError, ValueError):
        return False
    return True


def validate_plan(payload: PlanPayload) -> None:
    """Reject malformed identities, broken references and dependency cycles early."""
    phase_ids: set[str] = set()
    numbers: set[int] = set()
    ticket_ids: set[str] = set()
    for phase in payload.phases:
        if not _is_uuid(phase.id):
            raise ValidationFailure(
                "Phase ids must be UUIDs so identities survive replanning",
                code="invalid_dependency_graph",
                details={"phase_id": phase.id},
            )
        if phase.id in phase_ids:
            raise ValidationFailure(
                "Duplicate phase id",
                code="invalid_dependency_graph",
                details={"phase_id": phase.id},
            )
        if phase.number in numbers:
            raise ValidationFailure(
                "Duplicate phase number",
                code="invalid_dependency_graph",
                details={"phase_number": phase.number},
            )
        phase_ids.add(phase.id)
        numbers.add(phase.number)
        for ticket in phase.tickets:
            if not _is_uuid(ticket.id):
                raise ValidationFailure(
                    "Ticket ids must be UUIDs so identities survive replanning",
                    code="invalid_dependency_graph",
                    details={"ticket_id": ticket.id},
                )
            if ticket.id in ticket_ids:
                raise ValidationFailure(
                    "Duplicate ticket id",
                    code="invalid_dependency_graph",
                    details={"ticket_id": ticket.id},
                )
            ticket_ids.add(ticket.id)

    tickets: dict[str, PlanTicket] = {
        ticket.id: ticket for phase in payload.phases for ticket in phase.tickets
    }
    phase_of_ticket: dict[str, str] = {
        ticket.id: phase.id for phase in payload.phases for ticket in phase.tickets
    }
    if not tickets:
        raise ValidationFailure(
            "A RoadMap must contain at least one planned Ticket",
            code="invalid_dependency_graph",
        )

    for phase in payload.phases:
        for reference in (*phase.prerequisite_phase_ids, *phase.prerequisite_ticket_ids):
            if reference == phase.id:
                raise ValidationFailure(
                    "A Phase cannot depend on itself",
                    code="invalid_dependency_graph",
                    details={"phase_id": phase.id},
                )
        for reference in phase.prerequisite_phase_ids:
            if reference not in phase_ids:
                raise ValidationFailure(
                    "Phase dependency references an unknown Phase",
                    code="invalid_dependency_graph",
                    details={"phase_id": phase.id, "missing": reference},
                )
        for reference in phase.prerequisite_ticket_ids:
            if reference not in ticket_ids:
                raise ValidationFailure(
                    "Phase dependency references an unknown Ticket",
                    code="invalid_dependency_graph",
                    details={"phase_id": phase.id, "missing": reference},
                )
        for ticket in phase.tickets:
            _validate_ticket(ticket, phase_ids, ticket_ids)

    _reject_cycles(payload, tickets, phase_of_ticket)


def _validate_ticket(ticket: PlanTicket, phase_ids: set[str], ticket_ids: set[str]) -> None:
    if ticket.id in ticket.prerequisite_ticket_ids:
        raise ValidationFailure(
            "A Ticket cannot depend on itself",
            code="invalid_dependency_graph",
            details={"ticket_id": ticket.id},
        )
    for reference in ticket.prerequisite_phase_ids:
        if reference not in phase_ids:
            raise ValidationFailure(
                "Ticket dependency references an unknown Phase",
                code="invalid_dependency_graph",
                details={"ticket_id": ticket.id, "missing": reference},
            )
    for reference in ticket.prerequisite_ticket_ids:
        if reference not in ticket_ids:
            raise ValidationFailure(
                "Ticket dependency references an unknown Ticket",
                code="invalid_dependency_graph",
                details={"ticket_id": ticket.id, "missing": reference},
            )
    if ticket.required_actor == "human" and (
        not ticket.human_action_reason.strip() or not ticket.human_instructions.strip()
    ):
        raise ValidationFailure(
            "A human-only Ticket needs a reason and instructions",
            code="invalid_dependency_graph",
            details={"ticket_id": ticket.id},
        )


def _reject_cycles(
    payload: PlanPayload,
    tickets: dict[str, PlanTicket],
    phase_of_ticket: dict[str, str],
) -> None:
    """Cycle detection that includes implicit ordinary-Ticket-to-Phase relationships."""
    graph: dict[str, set[str]] = {}
    for phase in payload.phases:
        node = f"phase:{phase.id}"
        graph.setdefault(node, set())
        graph[node].update(f"phase:{other}" for other in phase.prerequisite_phase_ids)
        graph[node].update(f"ticket:{other}" for other in phase.prerequisite_ticket_ids)
    for ticket in tickets.values():
        node = f"ticket:{ticket.id}"
        graph.setdefault(node, set())
        graph[node].update(f"ticket:{other}" for other in ticket.prerequisite_ticket_ids)
        graph[node].update(f"phase:{other}" for other in ticket.prerequisite_phase_ids)
        if ticket.execution_mode == "normal":
            graph[node].add(f"phase:{phase_of_ticket[ticket.id]}")

    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 1:
            raise ValidationFailure(
                "Plan dependency graph contains a cycle",
                code="invalid_dependency_graph",
                details={"cycle": [*path, node]},
            )
        if state.get(node) == 2:
            return
        state[node] = 1
        for target in sorted(graph.get(node, ())):
            visit(target, [*path, node])
        state[node] = 2

    for node in sorted(graph):
        visit(node, [])


# --- readiness -----------------------------------------------------------------------------------


@dataclass(slots=True)
class Prerequisites:
    """What a Phase or a Ticket waits for, as its edges name them, in the order they were added."""

    phases: list[str] = field(default_factory=list[str])
    tickets: list[str] = field(default_factory=list[str])


type Dependencies = dict[str, Prerequisites]
"""Each source's prerequisites, keyed ``phase:<id>`` or ``ticket:<id>``; a node without edges is
absent."""


def dependencies(edges: list[LoopDependenciesRow]) -> Dependencies:
    result: Dependencies = {}
    for edge in edges:
        bucket = result.setdefault(f"{edge.source_type}:{edge.source_id}", Prerequisites())
        if edge.target_type == "phase":
            bucket.phases.append(edge.target_id)
        else:
            bucket.tickets.append(edge.target_id)
    return result


def items_by_phase(entries: list[PlannedItem]) -> dict[str, list[PlannedItem]]:
    grouped: dict[str, list[PlannedItem]] = {}
    for entry in entries:
        grouped.setdefault(entry.item.phase_id, []).append(entry)
    return grouped


def _json(raw: str) -> JsonValue:
    """A stored criteria or conditions list; an empty column reads as no entries."""
    value: JsonValue = json.loads(raw or "[]")
    return value


def phase_views(
    phases: list[LoopPhasesRow],
    grouped: dict[str, list[PlannedItem]],
    edges: Dependencies,
) -> list[PhaseView]:
    """Each Phase's state and entry blockers and each planned Ticket's readiness."""
    phase_by_id = {phase.id: phase for phase in phases}
    item_lookup = {entry.item.id: entry for entries in grouped.values() for entry in entries}
    completed_items = {
        item_id for item_id, entry in item_lookup.items() if entry.completed_at is not None
    }
    phase_complete: dict[str, bool] = {}

    def phase_prerequisites(phase_id: str) -> Prerequisites:
        return edges.get(f"phase:{phase_id}", Prerequisites())

    def item_prerequisites(item_id: str) -> Prerequisites:
        return edges.get(f"ticket:{item_id}", Prerequisites())

    def gates_in(phase_id: str) -> list[PlannedItem]:
        return [
            entry
            for entry in grouped.get(phase_id, [])
            if entry.item.execution_mode == "pre_phase_gate"
        ]

    def compute_phase_complete(phase_id: str) -> bool:
        entries = grouped.get(phase_id, [])
        if not entries:
            return all(
                phase_complete.get(reference, False)
                for reference in phase_prerequisites(phase_id).phases
            )
        return all(entry.completed_at is not None for entry in entries)

    def blockers_for(
        phase_ids: list[str], ticket_ids: list[str], *, include_gates_of: str | None
    ) -> list[Blocker]:
        blockers: list[Blocker] = []
        for reference in phase_ids:
            if not phase_complete.get(reference, False):
                phase = phase_by_id.get(reference)
                blockers.append(
                    {
                        "type": "phase",
                        "id": reference,
                        "reason": "prerequisite_phase_incomplete",
                        "phase_number": None if phase is None else phase.number,
                        "name": "" if phase is None else phase.name,
                    }
                )
        for reference in ticket_ids:
            if reference not in completed_items:
                entry = item_lookup.get(reference)
                blockers.append(
                    {
                        "type": "ticket",
                        "id": reference,
                        "key": None if entry is None else entry.item.key,
                        "title": "" if entry is None else entry.item.title,
                        "reason": "prerequisite_ticket_incomplete",
                    }
                )
        if include_gates_of is not None:
            blockers.extend(
                {
                    "type": "ticket",
                    "id": gate.item.id,
                    "key": gate.item.key,
                    "title": gate.item.title,
                    "reason": "pre_phase_gate_incomplete",
                }
                for gate in gates_in(include_gates_of)
                if gate.completed_at is None
            )
        return blockers

    # Phases are evaluated in dependency order; validation guarantees the graph is acyclic.
    remaining = list(phases)
    while remaining:
        progressed = False
        for phase in list(remaining):
            waits_for = phase_prerequisites(phase.id).phases
            if all(reference in phase_complete for reference in waits_for):
                phase_complete[phase.id] = compute_phase_complete(phase.id)
                remaining.remove(phase)
                progressed = True
        if not progressed:  # pragma: no cover - defensive, validation rejects cycles
            for phase in remaining:
                phase_complete[phase.id] = compute_phase_complete(phase.id)
            break

    downstream = downstream_phase_numbers(phases, grouped, edges)

    views: list[PhaseView] = []
    for phase in phases:
        prerequisites = phase_prerequisites(phase.id)
        entry_blockers = blockers_for(
            prerequisites.phases, prerequisites.tickets, include_gates_of=phase.id
        )
        entered = not entry_blockers
        if compute_phase_complete(phase.id):
            state = "complete"
        elif entered:
            state = "active"
        else:
            state = "pending"
        tickets: list[ReadinessItem] = []
        for entry in grouped.get(phase.id, []):
            item = entry.item
            explicit = item_prerequisites(item.id)
            blockers = blockers_for(explicit.phases, explicit.tickets, include_gates_of=None)
            if item.execution_mode == "normal" and not entered:
                blockers.extend(
                    [blocker for blocker in entry_blockers if blocker not in blockers]
                )
            tickets.append(
                {
                    "id": item.id,
                    "key": item.key,
                    "title": item.title,
                    "phase_id": item.phase_id,
                    "phase_number": item.phase_number,
                    "objective": item.objective,
                    "instructions": item.instructions,
                    "required_actor": item.required_actor,
                    "execution_mode": item.execution_mode,
                    "acceptance_criteria": _json(item.acceptance_criteria_json),
                    "expected_evidence": _json(item.expected_evidence_json),
                    "human_action_reason": item.human_action_reason,
                    "human_instructions": item.human_instructions,
                    "prerequisite_ticket_ids": explicit.tickets,
                    "prerequisite_phase_ids": explicit.phases,
                    "card_id": entry.card_id,
                    "completed_at": entry.completed_at,
                    "ready": not blockers,
                    "blockers": blockers,
                    "human_action_required": (
                        item.required_actor == "human" and entry.completed_at is None
                    ),
                    "downstream_phase_numbers": sorted(
                        downstream.get(f"ticket:{item.id}", set[int]())
                    ),
                }
            )
        views.append(
            {
                "id": phase.id,
                "number": phase.number,
                "name": phase.name,
                "objective": phase.objective,
                "entry_conditions": _json(phase.entry_conditions_json),
                "exit_conditions": _json(phase.exit_conditions_json),
                "prerequisite_phase_ids": prerequisites.phases,
                "prerequisite_ticket_ids": prerequisites.tickets,
                "state": state,
                "blocked_by": entry_blockers,
                "tickets": tickets,
            }
        )
    return views


def downstream_phase_numbers(
    phases: list[LoopPhasesRow],
    grouped: dict[str, list[PlannedItem]],
    edges: Dependencies,
) -> dict[str, set[int]]:
    """Phase numbers whose entry depends, directly or transitively, on a node."""
    phase_numbers = {phase.id: phase.number for phase in phases}
    prerequisites_of: dict[str, set[str]] = {}
    for phase in phases:
        node = f"phase:{phase.id}"
        prerequisites_of.setdefault(node, set())
        entry = edges.get(node, Prerequisites())
        prerequisites_of[node].update(f"phase:{reference}" for reference in entry.phases)
        prerequisites_of[node].update(f"ticket:{reference}" for reference in entry.tickets)
    for phase_id, entries in grouped.items():
        for planned in entries:
            node = f"ticket:{planned.item.id}"
            prerequisites_of.setdefault(node, set())
            entry = edges.get(node, Prerequisites())
            prerequisites_of[node].update(f"ticket:{reference}" for reference in entry.tickets)
            prerequisites_of[node].update(f"phase:{reference}" for reference in entry.phases)
            if planned.item.execution_mode == "normal":
                prerequisites_of[node].add(f"phase:{phase_id}")
    dependents: dict[str, set[str]] = {node: set() for node in prerequisites_of}
    for node, prerequisites in prerequisites_of.items():
        for prerequisite in prerequisites:
            dependents.setdefault(prerequisite, set()).add(node)
    result: dict[str, set[int]] = {}
    for node in prerequisites_of:
        seen: set[str] = set()
        stack = [node]
        numbers: set[int] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            kind, _, identifier = current.partition(":")
            if kind == "phase" and current != node and identifier in phase_numbers:
                numbers.add(phase_numbers[identifier])
            stack.extend(dependents.get(current, ()))
        result[node] = numbers
    return result


# --- the service ---------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopPlanService(PlanViews):
    """Registers, publishes and reads a Loop's plans; subclasses ``PlanViews`` so pyright checks
    the two views against the Protocol the other services take (PEP 544)."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- identity reservation --------------------------------------------------------------------

    def register_draft(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: PlanPayload,
        actor: ActorContext,
    ) -> PlanDraft:
        """Validate a candidate, reserve identities and store it as an unapproved plan revision.

        Its two RoadMap revisions are written afterwards in the same transaction, so they are
        empty until ``attach_revisions`` links them."""
        validate_plan(payload)
        revision = repos.plans.next_revision(loop.id)
        plan_id = self._new_id()
        now = self._now()
        canonical = _canonical_payload(repos, loop, payload, plan_id, revision)
        repos.plans.add(
            LoopPlansRow(
                id=plan_id,
                loop_id=loop.id,
                revision_number=revision,
                roadmap_ai_revision_id="",
                roadmap_revision_id="",
                approval_id=None,
                payload_json=json.dumps(canonical),
                content_hash=plan_hash(canonical),
                status="draft",
                created_at=now,
                activated_at=None,
                superseded_at=None,
            )
        )
        self._project(repos, loop.id, plan_id, canonical, actor)
        return {"plan_id": plan_id, "revision_number": revision, "payload": canonical}

    def _project(
        self,
        repos: BoardRepositories,
        loop_id: str,
        plan_id: str,
        canonical: CanonicalPlan,
        actor: ActorContext,
    ) -> None:
        """Project the plan onto its Phases, items and edges, keeping every known identity; the
        Loop's edges are those of its newest plan only."""
        now = self._now()
        repos.dependencies.clear(loop_id)
        for phase in canonical["phases"]:
            row = LoopPhasesRow(
                id=phase["id"],
                loop_id=loop_id,
                plan_id=plan_id,
                number=phase["number"],
                name=phase["name"],
                objective=phase["objective"],
                entry_conditions_json=json.dumps(phase["entry_conditions"]),
                exit_conditions_json=json.dumps(phase["exit_conditions"]),
                is_qa_phase=0,
                created_at=now,
            )
            if repos.phases.get(loop_id, phase["id"]) is None:
                repos.phases.add(row)
            else:
                repos.phases.update(row)
            for reference in phase["prerequisite_phase_ids"]:
                self._add_edge(repos, row, ("phase", phase["id"]), ("phase", reference), now)
            for reference in phase["prerequisite_ticket_ids"]:
                self._add_edge(repos, row, ("phase", phase["id"]), ("ticket", reference), now)
            for ticket in phase["tickets"]:
                _project_item(repos, row, ticket, now)
                for reference in ticket["prerequisite_ticket_ids"]:
                    edge = ("ticket", reference)
                    self._add_edge(repos, row, ("ticket", ticket["id"]), edge, now)
                for reference in ticket["prerequisite_phase_ids"]:
                    edge = ("phase", reference)
                    self._add_edge(repos, row, ("ticket", ticket["id"]), edge, now)
        self._log(
            repos,
            actor,
            "loop.plan_registered",
            loop_id,
            {"plan_id": plan_id, "revision": canonical["revision_number"]},
        )

    def _add_edge(
        self,
        repos: BoardRepositories,
        phase: LoopPhasesRow,
        source: tuple[str, str],
        target: tuple[str, str],
        now: str,
    ) -> None:
        """An edge of the plan ``phase`` belongs to: ``source`` waits for ``target``."""
        repos.dependencies.add(
            LoopDependenciesRow(
                id=self._new_id(),
                loop_id=phase.loop_id,
                plan_id=phase.plan_id,
                source_type=source[0],
                source_id=source[1],
                target_type=target[0],
                target_id=target[1],
                created_at=now,
            )
        )

    def attach_revisions(
        self,
        repos: BoardRepositories,
        plan_id: str,
        *,
        roadmap_ai_revision_id: str,
        roadmap_revision_id: str,
    ) -> None:
        repos.plans.attach_revisions(
            plan_id,
            roadmap_ai_revision_id=roadmap_ai_revision_id,
            roadmap_revision_id=roadmap_revision_id,
        )

    # --- publication -----------------------------------------------------------------------------

    def publish(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        plan_id: str,
        actor: ActorContext,
        *,
        approval_id: str | None,
    ) -> Publication:
        """Materialise every planned Ticket in one transaction. All or nothing."""
        plan = repos.plans.get(plan_id)
        if plan is None:
            raise NotFound("Plan not found")
        stored = _STORED_PLAN.validate_json(plan.payload_json)
        lists = repos.lists.for_loop(loop.id, include_archived=False)
        if not lists:
            raise Conflict(
                "The Loop has no column to publish Tickets into",
                code="loop_required",
                details={"loop_id": loop.id},
            )
        target_list = lists[0].id
        now = self._now()
        created: list[PublishedTicket] = []
        for phase in stored["phases"]:
            for ticket in phase["tickets"]:
                existing = repos.cards.get(ticket["id"])
                if existing is not None:
                    if existing.ticket_key != ticket["key"]:
                        raise Conflict(
                            "A card with this identity already exists with a different key",
                            code="plan_change_required",
                            details={"ticket_id": ticket["id"]},
                        )
                    created.append({"id": existing.id, "key": ticket["key"]})
                    continue
                repos.cards.add(
                    _planned_card(
                        ticket,
                        loop_id=loop.id,
                        list_id=target_list,
                        position=repos.cards.highest_position(target_list) + 1024,
                        phase_id=phase["id"],
                        plan_id=plan_id,
                        now=now,
                    )
                )
                created.append({"id": ticket["id"], "key": ticket["key"]})
        repos.plans.activate(loop.id, plan_id, approval_id=approval_id, now=now)
        repos.loops.set_current_plan(loop.id, plan_id, now=now)
        self._log(
            repos,
            actor,
            "loop.plan_published",
            loop.id,
            {"plan_id": plan_id, "tickets": len(created)},
        )
        return {"plan_id": plan_id, "tickets": created}

    # --- views -----------------------------------------------------------------------------------

    def plan_view(self, repos: BoardRepositories, loop: LoopsRow) -> PlanView:
        plan = repos.plans.active(loop.id)
        if plan is None:
            return {
                "loop_id": loop.id,
                "plan_id": None,
                "revision_number": None,
                "status": "none",
                "activated_at": None,
                "approved_at": None,
                "phases": [],
                "warnings": [],
            }
        return {
            "loop_id": loop.id,
            "plan_id": plan.id,
            "revision_number": plan.revision_number,
            "status": plan.status,
            "activated_at": plan.activated_at,
            "approved_at": plan.activated_at,
            "phases": _phases(repos, loop.id),
            "warnings": [],
        }

    def readiness(self, repos: BoardRepositories, loop: LoopsRow) -> Readiness:
        if repos.plans.active(loop.id) is None:
            return {
                "loop_id": loop.id,
                "stage": loop.stage,
                "execution_allowed": False,
                "blocked_reason": {
                    "code": "approval_required",
                    "message": "No approved plan has been published for this Loop",
                },
                "items": [],
                "phases": [],
            }
        phases = _phases(repos, loop.id)
        execution_allowed = loop.stage in EXECUTION_STAGES
        blocked_reason: BlockedReason | None = None
        if not execution_allowed:
            blocked_reason = {
                "code": "plan_change_required"
                if loop.stage == "replanning"
                else "approval_required",
                "message": "Execution transitions are frozen for this Loop stage",
                "stage": loop.stage,
            }
        return {
            "loop_id": loop.id,
            "stage": loop.stage,
            "execution_allowed": execution_allowed,
            "blocked_reason": blocked_reason,
            "items": [item for phase in phases for item in phase["tickets"]],
            "phases": phases,
        }

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        loop_id: str,
        changes: Mapping[str, object],
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="loop",
                entity_id=loop_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
        )


def _canonical_payload(
    repos: BoardRepositories,
    loop: LoopsRow,
    payload: PlanPayload,
    plan_id: str,
    revision: int,
) -> CanonicalPlan:
    """Attach server-allocated keys and Phase numbers to the model's structure. A Ticket the Loop
    already planned keeps its key and sequence; a new one takes the next sequence of its Phase."""
    phases: list[CanonicalPhase] = []
    counters: dict[int, int] = {}
    for phase in sorted(payload.phases, key=lambda entry: entry.number):
        tickets: list[CanonicalTicket] = []
        for ticket in phase.tickets:
            known = repos.plan_items.get(loop.id, ticket.id)
            if known is not None:
                sequence = known.ticket_sequence
                key = known.key
            else:
                sequence = counters.get(phase.number)
                if sequence is None:
                    sequence = repos.plan_items.next_sequence(loop.id, phase.number)
                counters[phase.number] = sequence + 1
                key = format_ticket_key(loop.key, phase_prefix(phase.name), phase.number, sequence)
            tickets.append(
                canonical_ticket(ticket, key=key, sequence=sequence, phase_number=phase.number)
            )
        phases.append(canonical_phase(phase, tickets))
    return {
        "schema_version": payload.schema_version,
        "summary": payload.summary,
        "loop_id": loop.id,
        "loop_key": loop.key,
        "plan_id": plan_id,
        "revision_number": revision,
        "phases": phases,
    }


def _project_item(
    repos: BoardRepositories, phase: LoopPhasesRow, ticket: CanonicalTicket, now: str
) -> None:
    """Store the item under its identity; a card already published from it follows the plan."""
    row = LoopPlanItemsRow(
        id=ticket["id"],
        loop_id=phase.loop_id,
        plan_id=phase.plan_id,
        phase_id=phase.id,
        phase_number=phase.number,
        key=ticket["key"],
        ticket_sequence=ticket["sequence"],
        title=ticket["title"],
        objective=ticket["objective"],
        instructions=ticket["instructions"],
        required_actor=ticket["required_actor"],
        execution_mode=ticket["execution_mode"],
        priority=ticket["priority"],
        acceptance_criteria_json=json.dumps(ticket["acceptance_criteria"]),
        expected_evidence_json=json.dumps(ticket["expected_evidence"]),
        human_action_reason=ticket["human_action_reason"],
        human_instructions=ticket["human_instructions"],
        created_at=now,
    )
    if repos.plan_items.get(phase.loop_id, ticket["id"]) is None:
        repos.plan_items.add(row)
    else:
        repos.plan_items.update(row)
        repos.cards.sync_plan_item(row, now=now)


def _planned_card(
    ticket: _StoredTicket,
    *,
    loop_id: str,
    list_id: str,
    position: int,
    phase_id: str,
    plan_id: str,
    now: str,
) -> CardsRow:
    """The Ticket card a planned Ticket becomes; it carries the plan item's identity."""
    return CardsRow(
        id=ticket["id"],
        list_id=list_id,
        title=ticket["title"],
        description=ticket["instructions"],
        position=position,
        priority=ticket["priority"],
        due_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
        archived_at=None,
        version=1,
        assignee_actor_id=None,
        assignee_type=None,
        assignee_name=None,
        assigned_at=None,
        assigned_by_actor_id=None,
        loop_id=loop_id,
        phase_id=phase_id,
        plan_item_id=ticket["id"],
        ticket_key=ticket["key"],
        kind="ticket",
        required_actor=ticket["required_actor"],
        execution_mode=ticket["execution_mode"],
        human_action_reason=ticket["human_action_reason"],
        human_instructions=ticket["human_instructions"],
        human_confirmed_at=None,
        human_confirmed_by_actor_id=None,
        plan_revision_id=plan_id,
    )


def _phases(repos: BoardRepositories, loop_id: str) -> list[PhaseView]:
    return phase_views(
        repos.phases.for_loop(loop_id),
        items_by_phase(repos.plan_items.with_cards(loop_id)),
        dependencies(repos.dependencies.for_loop(loop_id)),
    )


__all__ = [
    "CanonicalPhase",
    "CanonicalPlan",
    "CanonicalTicket",
    "LoopPlanService",
    "PlanDraft",
    "Publication",
    "validate_plan",
]
