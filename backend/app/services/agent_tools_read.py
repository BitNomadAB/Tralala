"""The worker tools that only read, and the helpers every tool handler shares.

The catalogue in ``agent_tools`` declares each tool's name, description, scopes and input schema;
the handlers here run the read-only entries (``read_board``, ``read_loop``, ``read_ticket`` and
``read_discussion``). Each takes ``(services, actor, args)``, opens with the ``actor.require``
checks of the scopes its entry declares and calls the same services as the REST routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.context import ActorContext
from ..core.errors import ValidationFailure

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services
    from .cards import CardEntry
    from .lists import ListEntry


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _require(args: dict[str, Any], key: str) -> str:
    value = _text(args.get(key))
    if value is None:
        raise ValidationFailure(f"{key} is required", details={"argument": key})
    return value


def _loop_lists(services: Services, board_id: str, loop_id: str) -> list[ListEntry]:
    return services.list.list(board_id, loop_id)


def _ticket_location(
    services: Services, board_id: str, card_id: str
) -> tuple[str, CardEntry]:
    loop_id, _ = services.card.locate(board_id, card_id)
    return loop_id, services.card.get(board_id, loop_id, card_id)


def _thread_view(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "discussion_id": thread["id"],
        "title": thread["title"],
        "status": thread["status"],
        "goal": thread["goal"],
        "card_id": thread.get("card_id"),
        "run_state": thread.get("run_state"),
        "messages": [
            {
                "id": message["id"],
                "author": message["author_name"],
                "author_type": message["author_type"],
                "content": message["content"],
                "created_at": message["created_at"],
            }
            for message in thread.get("messages", [])
        ],
        "positions": [
            {
                "agent": vote["display_name"],
                "position": vote["position"],
                "justification": vote["justification"],
            }
            for vote in thread.get("votes", [])
        ],
    }


# --- handlers ---------------------------------------------------------------


def _read_board(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("boards:read")
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    board = services.board.get(board_id)
    loops = services.loop.list(
        board_id,
        include_completed=bool(args.get("include_completed", False)),
        include_archived=False,
    )
    summaries = []
    for entry in loops:
        readiness = services.loop.readiness(board_id, entry["id"])
        summaries.append(
            {
                "id": entry["id"],
                "key": entry["key"],
                "name": entry["name"],
                "stage": entry["stage"],
                "goal": entry["goal"],
                "progress": entry.get("progress", {}),
                "execution_allowed": readiness["execution_allowed"],
                "blocked_reason": readiness["blocked_reason"],
            }
        )
    return {
        "board": {
            "id": board["id"],
            "name": board["name"],
            "status": board["status"],
        },
        "loops": summaries,
        "people": services.agent.assignable_people(),
        "agents": services.agent.askable_agents(board_id),
        "next_step": (
            "Call read_loop with one of these loop ids to read its documents and Tickets."
        ),
    }


def _read_loop(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    context = services.loop_document.context(board_id, loop_id)
    readiness = services.loop.readiness(board_id, loop_id)
    kinds = args.get("document_kinds")
    wanted = [str(kind) for kind in kinds] if isinstance(kinds, list) and kinds else None
    documents = {
        kind: value
        for kind, value in context["documents"].items()
        if wanted is None or kind in wanted
    }
    return {
        "loop": {
            "id": context["loop_id"],
            "key": context["loop_key"],
            "name": context["loop_name"],
            "goal": context["goal"],
            "stage": context["stage"],
        },
        "execution_allowed": readiness["execution_allowed"],
        "blocked_reason": readiness["blocked_reason"],
        "documents": documents,
        "plan": context["plan"],
        "columns": [
            {"id": entry["id"], "name": entry["name"]}
            for entry in _loop_lists(services, board_id, loop_id)
        ],
        "tickets": services.card.list(board_id, loop_id, limit=200)[0],
    }


def _read_ticket(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("cards:read")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    loop_id, card = _ticket_location(services, board_id, card_id)
    readiness = services.loop.readiness(board_id, loop_id)
    column = next(
        (
            entry["name"]
            for entry in _loop_lists(services, board_id, loop_id)
            if entry["id"] == card["list_id"]
        ),
        None,
    )
    allowed = ["comment_ticket", "assign_ticket", "move_ticket", "ask_agents"]
    if card["archived_at"]:
        allowed = []
    elif card["human_action_required"] and not card["completed_at"]:
        allowed = ["comment_ticket", "ask_agents"]
    elif card["plan_item_id"] and not card["ready"]:
        # A planned Ticket waits for its phase entry conditions; a manual one does not.
        allowed = [entry for entry in allowed if entry != "move_ticket"]
    return {
        "ticket": {
            "id": card["id"],
            "key": card["ticket_key"],
            "title": card["title"],
            "description": card["description"],
            "column": column,
            "list_id": card["list_id"],
            "priority": card["priority"],
            "labels": [label["name"] for label in card["labels"]],
            "assignee": (
                {
                    "id": card["assignee_actor_id"],
                    "name": card["assignee_name"],
                    "type": card["assignee_type"],
                }
                if card["assignee_actor_id"]
                else None
            ),
            "version": card["version"],
            "completed_at": card["completed_at"],
            "acceptance_criteria": card["acceptance_criteria"],
            "expected_evidence": card["expected_evidence"],
            "ready": card["ready"],
            "blockers": card["blockers"],
            "human_action_required": card["human_action_required"],
            "human_instructions": card["human_instructions"],
            "checklists": services.checklist.list(board_id, card_id),
            "comments": services.comment.list(board_id, card_id),
        },
        "loop": {
            "id": loop_id,
            "stage": readiness["stage"],
            "execution_allowed": readiness["execution_allowed"],
            "blocked_reason": readiness["blocked_reason"],
        },
        "allowed_actions": allowed,
    }


def _read_discussion(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("discussions:read")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    return _thread_view(services.discussion.get(board_id, discussion_id))


__all__ = [
    "_loop_lists",
    "_read_board",
    "_read_discussion",
    "_read_loop",
    "_read_ticket",
    "_require",
    "_text",
    "_thread_view",
    "_ticket_location",
]
