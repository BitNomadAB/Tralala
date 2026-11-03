"""The worker tool that finishes a Ticket: ``complete_ticket``.

A Ticket is done when ``completed_at`` is set, never because it sits in a column named Done. The
tool completes it through ``CardService.update`` (the version read for the worker, one retry on a
version conflict) and then comments the summary and the evidence, so a refused completion writes
nothing. The refusals are the service's: a human-only Ticket (the answer names who confirms it), an
unfinished prerequisite (``ticket_blocked`` with the blockers) and a Loop that is not executing.

``complete_ticket`` is typed on ``TicketCompleting``, the attributes of the composition root it
uses, so a unit test runs it with the real services on the typed fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..core.context import ActorContext
from ..core.errors import Forbidden, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardUpdate
from ..schemas.subresources import CommentCreate
from .agent_tools_read import ToolArguments, ToolResult, _require
from .agent_tools_write import DEDUPE_WINDOW_SECONDS, _seconds_since

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry, CardService
    from .loops import LoopService
    from .subresources import CommentEntry, CommentService


class TicketCompleting(Protocol):
    """What ``complete_ticket`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...

    @property
    def comment(self) -> CommentService: ...

    @property
    def loop(self) -> LoopService: ...


def completion_comment(summary: str, evidence: list[str]) -> str:
    """The comment that records a completion: the summary, then the evidence as a list."""
    if not evidence:
        return summary
    return summary + "\n\n**Evidence**\n\n" + "\n".join(f"- {item}" for item in evidence)


def _evidence(args: ToolArguments) -> list[str]:
    value = args.get("evidence")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationFailure(
            "evidence must be a list of strings", details={"argument": "evidence"}
        )
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _answer(
    services: TicketCompleting,
    board_id: str,
    card: CardEntry,
    comment: CommentEntry | None,
) -> ToolResult:
    loop = services.loop.get(board_id, card["loop_id"])
    return {
        "ticket": {
            "id": card["id"],
            "key": card["ticket_key"],
            "completed_at": card["completed_at"],
            "version": card["version"],
        },
        "comment_id": comment["id"] if comment is not None else None,
        "loop": {"stage": loop["stage"], "progress": loop["progress"]},
    }


def _completed_before(
    services: TicketCompleting, actor: ActorContext, board_id: str, card: CardEntry, content: str
) -> ToolResult:
    """A completed Ticket: the first answer when this is the same call again, else a refusal-free
    note that it was already done; nothing is written either way."""
    for comment in services.comment.list(board_id, card["id"]):
        if (
            comment["actor_id"] == actor.actor_id
            and comment["content"] == content
            and _seconds_since(comment["created_at"]) < DEDUPE_WINDOW_SECONDS
        ):
            return _answer(services, board_id, card, comment) | {"deduplicated": True}
    return _answer(services, board_id, card, None) | {"already_completed": True}


def _person_confirms(refusal: Forbidden, card: CardEntry) -> Forbidden:
    """The human-only refusal, saying who confirms the Ticket and what they were asked to do."""
    who = card["assignee_name"] or "a person on the board"
    key = card["ticket_key"] or "This Ticket"
    return Forbidden(
        f"{key} is work for a person: {who} confirms it in Tralala. Record what you found with "
        "comment_ticket.",
        code="human_action_required",
        details={
            **(refusal.details or {}),
            "ticket_key": card["ticket_key"],
            "confirmed_by": card["assignee_name"],
            "human_instructions": card["human_instructions"],
        },
    )


def complete_ticket(
    services: TicketCompleting, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    actor.require("comments:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    content = completion_comment(_require(args, "summary"), _evidence(args))
    loop_id, _ = services.card.locate(board_id, card_id)
    for attempt in range(2):
        card = services.card.get(board_id, loop_id, card_id)
        if card["completed_at"]:
            return _completed_before(services, actor, board_id, card, content)
        complete = CardUpdate(version=card["version"], completed=True)
        try:
            done = services.card.update(actor, board_id, loop_id, card_id, complete)
        except VersionConflict:
            if attempt:
                raise
            continue
        except Forbidden as refusal:
            if refusal.code != "human_action_required":
                raise
            raise _person_confirms(refusal, card) from None
        comment = services.comment.create(actor, board_id, card_id, CommentCreate(content=content))
        return _answer(services, board_id, done, comment)
    raise NotFound("Ticket not found")  # pragma: no cover - the loop returns or raises


__all__ = ["TicketCompleting", "complete_ticket", "completion_comment"]
