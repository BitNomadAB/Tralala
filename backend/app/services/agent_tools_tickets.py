"""The worker tools that write on a Ticket: ``create_ticket``, ``comment_ticket`` and
``complete_ticket``.

``create_ticket`` adds work a worker found while executing a Loop: outside the plan, keyed
``<LoopKey>-UNP-<nnn>``, never blocking readiness or completion (``CardService.create`` holds the
rule). A follow-up names the Ticket it came from, which gets a comment pointing at it. It may say
where the work is done, what it waits for (with a reason) and its area labels, by the names the
board has: an unknown label is refused with the names there are, never created.

A comment goes on a Ticket whether it is done or not; only a Loop or board that takes no writes
refuses it (the service's rule).

A Ticket is done when ``completed_at`` is set, never because it sits in a column named Done. The
tool completes it through ``CardService.update`` (the version read for the worker, one retry on a
version conflict) and comments the summary and the evidence. The comment is written whether or not
the Ticket can be completed: on a Ticket that is already done, and beside a refusal, so what the
worker did is on the Ticket either way; only a Loop or board that takes no writes refuses it. The
refusals are the service's: a human-only Ticket (the answer names who confirms it), an unfinished
prerequisite (``ticket_blocked`` with the blockers), an open wait (``ticket_waiting``, which a
person clears) and a Loop that is not executing.

``complete_ticket`` is typed on ``TicketCompleting``, the attributes of the composition root it
uses, so a unit test runs it with the real services on the typed fakes.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Protocol, TypeIs, get_args

from pydantic import ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardCreate, CardUpdate
from ..schemas.common import Priority
from ..schemas.subresources import CommentCreate
from .agent_tools_read import ToolArguments, ToolResult, _require, _text
from .agent_tools_write import DEDUPE_WINDOW_SECONDS, _seconds_since

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry, CardService
    from .lists import ListService
    from .loops import LoopService
    from .subresources import CommentEntry, CommentService

# The refusals a completion meets on a Ticket that still takes comments; any other error (a
# read-only Loop, an archived board, a missing Ticket) passes through and nothing is written.
REFUSALS = frozenset(
    {
        "human_action_required",
        "ticket_blocked",
        "ticket_waiting",
        "plan_change_required",
        "approval_required",
    }
)


class TicketCommenting(Protocol):
    """What ``comment_ticket`` uses of the composition root."""

    @property
    def card(self) -> CardService: ...

    @property
    def comment(self) -> CommentService: ...


class TicketCreating(TicketCommenting, Protocol):
    """What ``create_ticket`` uses of the composition root."""

    @property
    def list(self) -> ListService: ...


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


def _is_priority(value: object) -> TypeIs[Priority]:
    return value in get_args(Priority)


def _priority(args: ToolArguments) -> Priority:
    value = args.get("priority") or "none"
    if _is_priority(value):
        return value
    raise ValidationFailure(
        "Unknown priority", details={"argument": "priority", "allowed": list(get_args(Priority))}
    )


def _retry_key(loop_id: str, title: str, description: str, *rest: object) -> str:
    """The idempotency key of a ``create_ticket`` call: the same Ticket asked for again by the
    same actor answers the first one instead of a second Ticket."""
    material = json.dumps([loop_id, title, description, *rest])
    return "create_ticket:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _labels(args: ToolArguments) -> list[str]:
    value = args.get("labels")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationFailure("labels must be a list of names", details={"argument": "labels"})
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def create_ticket(
    services: TicketCreating, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    actor.require("comments:write")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    title = _require(args, "title")
    description = _text(args.get("description")) or ""
    summary = _text(args.get("summary")) or ""
    priority = _priority(args)
    origin_id = _text(args.get("follow_up_of"))
    origin: CardEntry | None = None
    if origin_id is not None:
        origin_loop, _ = services.card.locate(board_id, origin_id)
        origin = services.card.get(board_id, origin_loop, origin_id)
        description = f"Follow-up of {origin['ticket_key'] or origin['title']}: {description}"
    columns = services.list.list(board_id, loop_id)
    if not columns:
        raise ValidationFailure("The Loop has no column to add a Ticket to")
    work = {
        "workplace": _text(args.get("workplace")) or "unknown",
        "waiting_for": _text(args.get("waiting_for")) or "nothing",
        "waiting_reason": _text(args.get("waiting_reason")) or "",
    }
    labels = _labels(args)
    try:
        payload = CardCreate.model_validate(
            {
                "list_id": columns[0]["id"],
                "title": title,
                "description": description,
                "summary": summary,
                "priority": priority,
                "labels": labels,
                **work,
            }
        )
    except ValidationError as error:
        raise ValidationFailure(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
        ) from None
    created, replayed = services.card.create(
        actor,
        board_id,
        loop_id,
        payload,
        idempotency_key=_retry_key(
            loop_id, title, description, priority, origin_id or "", work, labels
        ),
        known_labels_only=True,
    )
    card = services.card.get(board_id, loop_id, str(created["id"]))
    answer: ToolResult = {
        "ticket": {
            "id": card["id"],
            "key": card["ticket_key"],
            "title": card["title"],
            "column": columns[0]["name"],
            "version": card["version"],
            "state": card["state"],
            "workplace": card["workplace"],
            "labels": [label["name"] for label in card["labels"]],
        },
        "unplanned": card["ticket_key"] is not None,
    }
    if origin is not None:
        note = f"Follow-up: {card['ticket_key'] or card['title']} - {card['title']}"
        kept = _recent(services, actor, board_id, origin["id"], note)
        if kept is None and not replayed:
            kept = services.comment.create(
                actor, board_id, origin["id"], CommentCreate(content=note)
            )
        answer["follow_up_of"] = {
            "id": origin["id"],
            "key": origin["ticket_key"],
            "comment_id": kept["id"] if kept is not None else None,
        }
    if replayed:
        answer["deduplicated"] = True
    return answer


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
    "TicketCreating",
    "comment_ticket",
    "complete_ticket",
    "completion_comment",
    "create_ticket",
]
