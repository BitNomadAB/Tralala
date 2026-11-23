"""What the Loop and Ticket services read from a Loop's approved plan: its view and its readiness.

The plan service computes both (``LoopPlanService``); the Loop and Ticket services depend on this
Protocol only, so their rules run in a unit test with a fake plan. The shapes are the JSON the
plan and readiness routes return.
"""

from __future__ import annotations

from typing import NotRequired, Protocol, TypedDict

from pydantic import JsonValue

from ..db.generated.board import CardsRow, LoopsRow
from ..repositories.board import BoardRepositories
from .ticket_state import TicketState, loop_closed, ticket_state


class Blocker(TypedDict):
    """Why a Ticket or a Phase cannot start: an incomplete Phase, Ticket or pre-Phase gate."""

    type: str
    id: str
    reason: str
    phase_number: NotRequired[int | None]
    name: NotRequired[str]
    key: NotRequired[str | None]
    title: NotRequired[str]


class ReadinessItem(TypedDict):
    """A planned Ticket and whether it may start."""

    id: str
    key: str
    title: str
    phase_id: str
    phase_number: int
    objective: str
    instructions: str
    required_actor: str
    execution_mode: str
    acceptance_criteria: JsonValue
    expected_evidence: JsonValue
    human_action_reason: str
    human_instructions: str
    prerequisite_ticket_ids: list[str]
    prerequisite_phase_ids: list[str]
    card_id: str | None
    completed_at: str | None
    ready: bool
    blockers: list[Blocker]
    human_action_required: bool
    downstream_phase_numbers: list[int]
    workplace: str
    waiting_for: str
    state: TicketState | None
    """ready, needs_input or blocked from the card's wait and the blockers, or not_done once the
    Loop is closed (``ticket_state``)."""


class PhaseView(TypedDict):
    id: str
    number: int
    name: str
    objective: str
    entry_conditions: JsonValue
    exit_conditions: JsonValue
    prerequisite_phase_ids: list[str]
    prerequisite_ticket_ids: list[str]
    state: str
    blocked_by: list[Blocker]
    tickets: list[ReadinessItem]


class PlanWarning(TypedDict):
    code: str
    message: str


class BlockedReason(TypedDict):
    code: str
    message: str
    stage: NotRequired[str]


class Readiness(TypedDict):
    """Whether delivery may run in the Loop's stage, and each planned Ticket's readiness."""

    loop_id: str
    stage: str
    execution_allowed: bool
    blocked_reason: BlockedReason | None
    items: list[ReadinessItem]
    phases: list[PhaseView]


class UnplannedTicket(TypedDict):
    """A Ticket added outside the Loop's plan: it never blocks readiness or completion."""

    id: str
    key: str | None
    title: str
    completed_at: str | None
    archived_at: str | None
    workplace: str
    waiting_for: str
    state: TicketState | None
    """Outside the plan nothing blocks it: only its own wait can, until the Loop is closed
    (``ticket_state``)."""


class OpenDeliveryTicket(TypedDict):
    """A Ticket a plan published that is not completed. Accepting the implementation is refused
    while there is one, unless the person accepts it without them."""

    id: str
    ticket_key: str | None
    title: str
    completed_at: str | None
    archived_at: str | None


class LoopReadiness(Readiness):
    """Readiness as the Loop answers it: the plan's Tickets, the work outside the plan and the
    delivery Tickets that are not completed."""

    unplanned: list[UnplannedTicket]
    open_delivery: list[OpenDeliveryTicket]


def delivery_tickets(repos: BoardRepositories, loop_id: str) -> list[CardsRow]:
    """The Loop's delivery Tickets by key: every card a plan published, an archived one and one
    an earlier plan left behind included. A QA Task and a Ticket outside the plan are not
    delivery."""
    return [card for card in repos.archive.tickets(loop_id) if card.kind == "ticket"]


def open_delivery(repos: BoardRepositories, loop_id: str) -> list[OpenDeliveryTicket]:
    """The delivery Tickets that are not completed: work the Loop planned and has not finished."""
    return [
        {
            "id": card.id,
            "ticket_key": card.ticket_key,
            "title": card.title,
            "completed_at": card.completed_at,
            "archived_at": card.archived_at,
        }
        for card in delivery_tickets(repos, loop_id)
        if card.completed_at is None
    ]


def unplanned_tickets(repos: BoardRepositories, loop: LoopsRow) -> list[UnplannedTicket]:
    """The manual Tickets of a Loop that executes a plan, archived ones included; a Loop without
    a plan has nothing outside it."""
    if not loop.current_plan_id:
        return []
    closed = loop_closed(loop)
    return [
        {
            "id": card.id,
            "key": card.ticket_key,
            "title": card.title,
            "completed_at": card.completed_at,
            "archived_at": card.archived_at,
            "workplace": card.workplace,
            "waiting_for": card.waiting_for,
            "state": ticket_state(
                completed=card.completed_at is not None,
                waiting_for=card.waiting_for,
                blocked=False,
                loop_closed=closed,
            ),
        }
        for card in repos.cards.manual(loop.id)
    ]


class PlanView(TypedDict):
    """The Loop's active plan by Phase (``status`` ``none`` when there is none)."""

    loop_id: str
    plan_id: str | None
    revision_number: int | None
    status: str
    activated_at: str | None
    approved_at: str | None
    phases: list[PhaseView]
    warnings: list[PlanWarning]


class PlanViews(Protocol):
    """The plan views, read inside the caller's reader or writer."""

    def plan_view(self, repos: BoardRepositories, loop: LoopsRow) -> PlanView: ...

    def readiness(self, repos: BoardRepositories, loop: LoopsRow) -> Readiness: ...
