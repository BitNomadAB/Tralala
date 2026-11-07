"""A Ticket's state: ready, needs input or blocked, computed from what it waits for and its plan.

Tralala never does the work and never looks as if it does: a person owns every Ticket, and a coding
agent is a tool in that person's session. So the state describes the Ticket, never who does it.
Three questions stay apart: where the work is done (``workplace``), what the Ticket waits for
(``waiting_for``, with a reason) and its area (labels). The state is computed from the wait and the
plan's blockers on every read and is never stored or set by hand:

- ``needs_input``: it waits for a decision, information or access, which a person can give now;
- ``blocked``: the plan's blockers are not empty (an earlier Ticket, a Phase, a pre-Phase gate),
  or it waits for a third party;
- ``ready``: neither.

``needs_input`` wins over ``blocked``: a person can answer now even when other work is unfinished.
A completed Ticket has no state (``None``). ``human_action_required`` stays apart: it says the task
itself is a person's, and such a Ticket can be ``ready``.
"""

from __future__ import annotations

from typing import Final, Literal, TypedDict, get_args

from ..core.errors import Conflict
from ..db.generated.board import CardsRow

TicketState = Literal["ready", "needs_input", "blocked"]
TICKET_STATES: Final[tuple[str, ...]] = get_args(TicketState)
INPUT_WAITS: Final = ("decision", "information", "access")
"""What a person can answer now: a Ticket waiting for one of these needs input."""


def ticket_state(*, completed: bool, waiting_for: str, blocked: bool) -> TicketState | None:
    """The state of an open Ticket; ``None`` once it is completed."""
    if completed:
        return None
    if waiting_for in INPUT_WAITS:
        return "needs_input"
    if blocked or waiting_for == "third_party":
        return "blocked"
    return "ready"


def needs_person(state: str | None, *, human_action_required: bool) -> bool:
    """What waits for a person: an answer (``needs_input``), or a person's task that may start."""
    return state == "needs_input" or (state == "ready" and human_action_required)


class TicketWait(TypedDict):
    """What a Ticket waits for, why, and who set it when; ``waiting_for`` ``nothing`` has none."""

    waiting_for: str
    reason: str
    set_by: str | None
    set_at: str | None


def ticket_wait(card: CardsRow) -> TicketWait:
    return {
        "waiting_for": card.waiting_for,
        "reason": card.waiting_reason,
        "set_by": card.waiting_set_by,
        "set_at": card.waiting_set_at,
    }


def ensure_not_waiting(card: CardsRow) -> None:
    """Completing a Ticket with an open wait is refused (``409 ticket_waiting``), naming the wait:
    a person clears the wait first, so nobody completes work past a question left open."""
    if card.waiting_for == "nothing":
        return
    raise Conflict(
        f"This Ticket waits for {card.waiting_for.replace('_', ' ')}: clear the wait first",
        code="ticket_waiting",
        details={"ticket_key": card.ticket_key, "wait": dict(ticket_wait(card))},
    )


__all__ = [
    "INPUT_WAITS",
    "TICKET_STATES",
    "TicketState",
    "TicketWait",
    "ensure_not_waiting",
    "needs_person",
    "ticket_state",
    "ticket_wait",
]
