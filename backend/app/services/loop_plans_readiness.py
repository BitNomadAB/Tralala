"""Readiness: each Phase's state and entry blockers, each planned Ticket's readiness and the
Phases downstream of it, from the Phases, the plan items with their cards and the dependency
edges. ``loop_plans`` re-exports every name here, so callers keep importing them from there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import JsonValue

from ..db.generated.board import LoopDependenciesRow, LoopPhasesRow
from ..repositories.loop_plans import PlannedItem
from .plan_views import Blocker, PhaseView, ReadinessItem

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
