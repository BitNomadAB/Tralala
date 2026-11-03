"""The worker tools that write on a Ticket: ``comment_ticket`` and ``complete_ticket``.

A comment goes on a Ticket whether it is done or not; only a Loop or board that takes no writes
refuses it (the service's rule).

A Ticket is done when ``completed_at`` is set, never because it sits in a column named Done. The
tool completes it through ``CardService.update`` (the version read for the worker, one retry on a
version conflict) and comments the summary and the evidence. The comment is written whether or not
the Ticket can be completed: on a Ticket that is already done, and beside a refusal, so what the
worker did is on the Ticket either way; only a Loop or board that takes no writes refuses it. The
refusals are the service's: a human-only Ticket (the answer names who confirms it), an unfinished
prerequisite (``ticket_blocked`` with the blockers) and a Loop that is not executing.

``complete_ticket`` is typed on ``TicketCompleting``, the attributes of the composition root it
uses, so a unit test runs it with the real services on the typed fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..core.context import ActorContext
from ..core.errors import ApiError, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardUpdate
from ..schemas.subresources import CommentCreate
from .agent_tools_read import ToolArguments, ToolResult, _require
from .agent_tools_write import DEDUPE_WINDOW_SECONDS, _seconds_since

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry, CardService
    from .loops import LoopService
    from .subresources import CommentEntry, CommentService

# The refusals a completion meets on a Ticket that still takes comments; any other error (a
# read-only Loop, an archived board, a missing Ticket) passes through and nothing is written.
REFUSALS = frozenset(
    {"human_action_required", "ticket_blocked", "plan_change_required", "approval_required"}
)


class TicketCommenting(Protocol):
    """What ``comment_ticket`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...

    @property
    def comment(self) -> CommentService: ...


class TicketCompleting(TicketCommenting, Protocol):
    """What ``complete_ticket`` uses of the composition root."""

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


def _recent(
    services: TicketCommenting, actor: ActorContext, board_id: str, card_id: str, content: str
) -> CommentEntry | None:
    """The same comment by the same actor within the dedupe window: this call is a retry."""
    for comment in services.comment.list(board_id, card_id):
        if (
            comment["actor_id"] == actor.actor_id
            and comment["content"] == content
            and _seconds_since(comment["created_at"]) < DEDUPE_WINDOW_SECONDS
        ):
            return comment
    return None


def _refused(refusal: ApiError, card: CardEntry, comment: CommentEntry) -> ApiError:
    """The service's refusal, saying the summary was kept as a comment; a human-only Ticket also
    says who confirms it and what they were asked to do."""
    details: dict[str, object] = {**(refusal.details or {}), "comment_id": comment["id"]}
    message = refusal.message
    if refusal.code == "human_action_required":
        who = card["assignee_name"] or "a person on the board"
        message = f"{card['ticket_key'] or 'This Ticket'} is work for a person: {who} confirms it"
        details |= {
            "ticket_key": card["ticket_key"],
            "confirmed_by": card["assignee_name"],
            "human_instructions": card["human_instructions"],
        }
    return type(refusal)(
        f"{message}. Your summary is saved as a comment on the Ticket.",
        code=refusal.code,
        details=details,
    )


def comment_ticket(
    services: TicketCommenting, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("comments:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    content = _require(args, "content")
    # Resolving the Ticket proves it belongs to this board before anything is written.
    services.card.locate(board_id, card_id)
    existing = _recent(services, actor, board_id, card_id, content)
    if existing is not None:
        return {
            "id": existing["id"],
            "actor": existing["actor_name"],
            "content": existing["content"],
            "created_at": existing["created_at"],
            "deduplicated": True,
        }
    created = services.comment.create(actor, board_id, card_id, CommentCreate(content=content))
    return {
        "id": created["id"],
        "actor": created["actor_name"],
        "content": created["content"],
        "created_at": created["created_at"],
    }


def complete_ticket(
    services: TicketCompleting, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    actor.require("comments:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    content = completion_comment(_require(args, "summary"), _evidence(args))
    loop_id, _ = services.card.locate(board_id, card_id)
    earlier = _recent(services, actor, board_id, card_id, content)

    def comment() -> CommentEntry:
        if earlier is not None:
            return earlier
        return services.comment.create(actor, board_id, card_id, CommentCreate(content=content))

    for attempt in range(2):
        card = services.card.get(board_id, loop_id, card_id)
        if card["completed_at"]:
            # Done already: the summary is still worth keeping, once.
            mark = {"deduplicated": True} if earlier else {"already_completed": True}
            return _answer(services, board_id, card, comment()) | mark
        complete = CardUpdate(version=card["version"], completed=True)
        try:
            done = services.card.update(actor, board_id, loop_id, card_id, complete)
        except VersionConflict:
            if attempt:
                raise
            continue
        except ApiError as refusal:
            if refusal.code not in REFUSALS:
                raise
            raise _refused(refusal, card, comment()) from None
        return _answer(services, board_id, done, comment())
    raise NotFound("Ticket not found")  # pragma: no cover - the loop returns or raises


__all__ = [
    "REFUSALS",
    "TicketCommenting",
    "TicketCompleting",
    "comment_ticket",
    "complete_ticket",
    "completion_comment",
]
