"""The canonical plan: a RoadMap's structure as the plan revision stores it, with the
server-allocated Ticket keys, sequences and Phase numbers, its content hash, and what registering
and publishing a plan return. ``loop_plans`` re-exports every name here, so callers keep importing
them from there.
"""

from __future__ import annotations

import hashlib
import json
from typing import TypedDict

from ..schemas.loops import PlanPhase, PlanTicket

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
    workplace: str
    waiting_for: str
    waiting_reason: str
    labels: list[str]
    summary: str
    why: str
    if_skipped: str
    pros: list[str]
    cons: list[str]
    steps: list[str]
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
    """What publishing did: the plan's Tickets, and the cards of an earlier plan it leaves out,
    removed when nobody had touched them and kept otherwise."""

    plan_id: str
    tickets: list[PublishedTicket]
    removed: list[PublishedTicket]
    kept: list[PublishedTicket]


class Withdrawal(TypedDict):
    """What withdrawing the plan in force did to the cards plans published: removed when nobody
    had touched them, archived otherwise."""

    removed: list[PublishedTicket]
    archived: list[PublishedTicket]


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
        "workplace": ticket.workplace,
        "waiting_for": ticket.waiting_for,
        "waiting_reason": ticket.waiting_reason,
        "labels": list(ticket.labels),
        "summary": ticket.summary,
        "why": ticket.why,
        "if_skipped": ticket.if_skipped,
        "pros": list(ticket.pros),
        "cons": list(ticket.cons),
        "steps": list(ticket.steps),
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
