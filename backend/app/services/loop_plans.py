"""Structured RoadMaps: validation, identity reservation, publication and readiness.

The structured plan revision is authoritative. ``loop_phases``, ``loop_plan_items`` and
``loop_dependencies`` are validated projections that carry stable identities; live cards are the
execution projection of the active plan.

``LoopPlanService`` works inside its caller's reader or writer: every method takes the board
repositories of that unit of work, so a plan is registered, published and read in the caller's
transaction. It is the ``PlanViews`` the Loop, Ticket and search services read, and it takes the
clock and the id source as arguments, so every rule here runs in a unit test without a database.

The canonical plan lives in ``loop_plans_canonical``, validation in ``loop_plans_validation`` and
readiness in ``loop_plans_readiness``; this module keeps ``LoopPlanService`` and re-exports their
names, so every caller imports them from here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from typing import NotRequired, TypedDict
from uuid import uuid4

from pydantic import TypeAdapter

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound
from ..db.generated.board import (
    CardsRow,
    LoopDependenciesRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
    LoopsRow,
)
from ..repositories.board import BoardRepositories
from ..schemas.loops import PlanPayload
from .activity import activity_entry
from .cards_writes import known_label_ids
from .loop_identifiers import format_ticket_key, phase_prefix
from .loop_plans_canonical import (
    CanonicalPhase,
    CanonicalPlan,
    CanonicalTicket,
    PlanDraft,
    Publication,
    PublishedTicket,
    Withdrawal,
    canonical_phase,
    canonical_ticket,
    plan_hash,
)
from .loop_plans_readiness import (
    Dependencies,
    Prerequisites,
    dependencies,
    downstream_phase_numbers,
    items_by_phase,
    phase_views,
)
from .loop_plans_validation import validate_plan
from .loops import EXECUTION_STAGES
from .plan_views import BlockedReason, PhaseView, PlanView, PlanViews, Readiness
from .ticket_face import face_to_text, make_face
from .ticket_summaries import summary_basis


# What publishing reads back from a stored payload; any other key is left alone.
class _StoredTicket(TypedDict):
    id: str
    key: str
    title: str
    summary: NotRequired[str]  # absent from a plan stored before Tickets had summaries
    instructions: str
    priority: str
    required_actor: str
    execution_mode: str
    human_action_reason: str
    human_instructions: str
    # absent from a plan stored before Tickets said where their work is done and what they wait for
    workplace: NotRequired[str]
    waiting_for: NotRequired[str]
    waiting_reason: NotRequired[str]
    labels: NotRequired[list[str]]
    # absent from a plan stored before Tickets had a face for people
    why: NotRequired[str]
    if_skipped: NotRequired[str]
    pros: NotRequired[list[str]]
    cons: NotRequired[list[str]]
    steps: NotRequired[list[str]]


class _StoredPhase(TypedDict):
    id: str
    tickets: list[_StoredTicket]


class _StoredPlan(TypedDict):
    phases: list[_StoredPhase]


_STORED_PLAN = TypeAdapter(_StoredPlan)


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
        *,
        drop_unknown_labels: bool = False,
    ) -> PlanDraft:
        """Validate a candidate, reserve identities and store it as an unapproved plan revision.

        A planned Ticket's labels are names the board has: an unknown one is refused with the
        names there are, or, for a generated RoadMap (``drop_unknown_labels``) whose model was
        given the names and checked against them, left out at publication.

        Its two RoadMap revisions are written afterwards in the same transaction, so they are
        empty until ``attach_revisions`` links them."""
        validate_plan(payload)
        for phase in payload.phases:
            for ticket in phase.tickets:
                known_label_ids(repos, ticket.labels, drop_unknown=drop_unknown_labels)
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
        """Materialise every planned Ticket in one transaction. All or nothing. A card an earlier
        plan published that this one leaves out is removed when nobody has touched it
        (``untouched``), and kept, with what was done on it, otherwise."""
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
                        publisher=actor.actor_id,
                    )
                )
                # A label removed from the board since the plan was written is left out.
                labels = known_label_ids(repos, ticket.get("labels", []), drop_unknown=True)
                if labels:
                    repos.cards.set_labels(ticket["id"], labels)
                created.append({"id": ticket["id"], "key": ticket["key"]})
        planned = {ticket["id"] for phase in stored["phases"] for ticket in phase["tickets"]}
        removed, kept = _replace_earlier_cards(repos, loop.id, planned)
        repos.plans.activate(loop.id, plan_id, approval_id=approval_id, now=now)
        repos.loops.set_current_plan(loop.id, plan_id, now=now)
        changes: dict[str, object] = {"plan_id": plan_id, "tickets": len(created)}
        if removed or kept:
            changes["removed"] = [entry["key"] for entry in removed]
            changes["kept"] = [entry["key"] for entry in kept]
        self._log(repos, actor, "loop.plan_published", loop.id, changes)
        return {"plan_id": plan_id, "tickets": created, "removed": removed, "kept": kept}

    def withdraw(self, repos: BoardRepositories, loop_id: str) -> Withdrawal:
        """Take the plan off the Kanban, as a RoadMap reset does: no plan is in force any more, and
        every card a plan published leaves the Kanban, deleted when nobody has touched it
        (``untouched``) and archived otherwise, so nothing anybody did on it is lost. A card added
        outside the plan stays. The plan items stay stored, so a Ticket key is never used again."""
        now = self._now()
        repos.plans.retire(loop_id, now=now)
        repos.loops.set_current_plan(loop_id, None, now=now)
        cards = repos.cards.planned(loop_id)
        additions = repos.cards.additions([card.id for card in cards])
        removed: list[PublishedTicket] = []
        archived: list[PublishedTicket] = []
        for card in cards:
            entry: PublishedTicket = {"id": card.id, "key": card.ticket_key or card.id}
            if untouched(card, additions.get(card.id, 0)):
                repos.cards.delete(card.id)
                removed.append(entry)
            elif card.archived_at is None:
                repos.cards.archive(card.id, now=now)
                archived.append(entry)
        return {"removed": removed, "archived": archived}

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


def untouched(card: CardsRow, additions: int) -> bool:
    """Whether nobody has worked on a published card: it was never changed (version 1), nobody
    has it, it is not completed, confirmed or archived, and nothing was added to it (a comment, a
    checklist, an attachment, a note or a discussion)."""
    return (
        card.version == 1
        and card.assignee_actor_id is None
        and card.completed_at is None
        and card.human_confirmed_at is None
        and card.archived_at is None
        and additions == 0
    )


def _replace_earlier_cards(
    repos: BoardRepositories, loop_id: str, planned: Collection[str]
) -> tuple[list[PublishedTicket], list[PublishedTicket]]:
    """The cards an earlier plan of the Loop published that ``planned`` leaves out: the
    untouched ones are deleted and the others stay. Answers both, in creation order."""
    earlier = [card for card in repos.cards.planned(loop_id) if card.plan_item_id not in planned]
    additions = repos.cards.additions([card.id for card in earlier])
    removed: list[PublishedTicket] = []
    kept: list[PublishedTicket] = []
    for card in earlier:
        entry: PublishedTicket = {"id": card.id, "key": card.ticket_key or card.id}
        if untouched(card, additions.get(card.id, 0)):
            repos.cards.delete(card.id)
            removed.append(entry)
        else:
            kept.append(entry)
    return removed, kept


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
        summary=ticket["summary"],
        required_actor=ticket["required_actor"],
        execution_mode=ticket["execution_mode"],
        priority=ticket["priority"],
        acceptance_criteria_json=json.dumps(ticket["acceptance_criteria"]),
        expected_evidence_json=json.dumps(ticket["expected_evidence"]),
        human_action_reason=ticket["human_action_reason"],
        human_instructions=ticket["human_instructions"],
        created_at=now,
        workplace=ticket["workplace"],
        waiting_for=ticket["waiting_for"],
        waiting_reason=ticket["waiting_reason"],
        face=face_to_text(
            make_face(
                ticket["why"], ticket["if_skipped"], ticket["pros"], ticket["cons"], ticket["steps"]
            )
        ),
    )
    if repos.plan_items.get(phase.loop_id, ticket["id"]) is None:
        repos.plan_items.add(row)
    else:
        repos.plan_items.update(row)
        repos.cards.sync_plan_item(
            row, now=now, summary_basis=summary_basis(row.title, row.instructions)
        )


def _planned_card(
    ticket: _StoredTicket,
    *,
    loop_id: str,
    list_id: str,
    position: int,
    phase_id: str,
    plan_id: str,
    now: str,
    publisher: str,
) -> CardsRow:
    """The Ticket card a planned Ticket becomes; it carries the plan item's identity, the
    RoadMap's summary and face of it and its starting workplace and wait (set by whoever published
    the plan, when the plan gave one). A plan stored before the face existed publishes none."""
    summary = ticket.get("summary", "")
    waiting_for = ticket.get("waiting_for", "nothing")
    waiting = waiting_for != "nothing"
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
        summary=summary,
        summary_source="plan" if summary else "",
        summary_basis_sha256=(
            summary_basis(ticket["title"], ticket["instructions"]) if summary else ""
        ),
        workplace=ticket.get("workplace", "unknown"),
        waiting_for=waiting_for,
        waiting_reason=ticket.get("waiting_reason", "") if waiting else "",
        waiting_set_at=now if waiting else None,
        waiting_set_by=publisher if waiting else None,
        face=face_to_text(
            make_face(
                ticket.get("why", ""),
                ticket.get("if_skipped", ""),
                ticket.get("pros", []),
                ticket.get("cons", []),
                ticket.get("steps", []),
            )
        ),
    )


def _phases(repos: BoardRepositories, loop_id: str) -> list[PhaseView]:
    return phase_views(
        repos.phases.of_active_plan(loop_id),
        items_by_phase(repos.plan_items.active_with_cards(loop_id)),
        dependencies(repos.dependencies.for_loop(loop_id)),
    )


__all__ = [
    "CanonicalPhase",
    "CanonicalPlan",
    "CanonicalTicket",
    "Dependencies",
    "LoopPlanService",
    "PlanDraft",
    "Prerequisites",
    "Publication",
    "PublishedTicket",
    "Withdrawal",
    "canonical_phase",
    "canonical_ticket",
    "dependencies",
    "downstream_phase_numbers",
    "items_by_phase",
    "phase_views",
    "plan_hash",
    "untouched",
    "validate_plan",
]
