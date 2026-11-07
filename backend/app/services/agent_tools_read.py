"""The worker tools that only read, and the helpers every tool handler shares.

The catalogue in ``agent_tools`` declares each tool's name, description, scopes and input schema;
the handlers here run the read-only entries (``list_boards``, ``read_board``,
``read_ticket`` and ``search_tickets``; ``read_discussion`` lives in ``agent_tools_discussions``).
Each takes
``(services, actor, args)``, opens with the ``actor.require`` checks of the scopes its entry
declares and calls the same services as the REST routes.

The two listing handlers are public and typed on the attributes of the composition root they use
(``BoardListing``, ``TicketSearching``), so a unit test runs them with the real services on the
typed fakes; the others still take the whole ``Services``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from .search import search_engine

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services
    from .boards import BoardService
    from .cards import CardEntry
    from .lists import ListEntry, ListService
    from .loops import LoopService
    from .search import SearchHit, SearchService

# A tool's arguments: the JSON object an MCP ``tools/call`` carried, untrusted.
type ToolArguments = Mapping[str, JsonValue]
# A tool's answer: an object built from the services' entries, sent back as JSON.
type ToolResult = dict[str, object]

# The listing tools are the way in, not a report: at most this many boards, and this many hits.
BOARD_LIST_LIMIT = 100
SEARCH_LIMIT = 100
SEARCH_DEFAULT = 25


class BoardListing(Protocol):
    """What ``list_boards`` uses of the composition root."""

    @property
    def board(self) -> BoardService: ...


class TicketSearching(Protocol):
    """What ``search_tickets`` uses of the composition root."""

    @property
    def search(self) -> SearchService: ...

    @property
    def loop(self) -> LoopService: ...

    @property
    def list(self) -> ListService: ...


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _require(args: ToolArguments, key: str) -> str:
    value = _text(args.get(key))
    if value is None:
        raise ValidationFailure(f"{key} is required", details={"argument": key})
    return value


def _whole_number(args: ToolArguments, key: str, *, default: int, maximum: int) -> int:
    """An optional whole number from 1 to ``maximum``; a refusal names the argument."""
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ValidationFailure(f"{key} must be a whole number", details={"argument": key})
    number = int(value)
    if not 1 <= number <= maximum:
        raise ValidationFailure(
            f"{key} must be between 1 and {maximum}",
            details={"argument": key, "minimum": 1, "maximum": maximum},
        )
    return number


def _loop_lists(services: Services, board_id: str, loop_id: str) -> list[ListEntry]:
    return services.list.list(board_id, loop_id)


def _ticket_location(
    services: Services, board_id: str, card_id: str
) -> tuple[str, CardEntry]:
    loop_id, _ = services.card.locate(board_id, card_id)
    return loop_id, services.card.get(board_id, loop_id, card_id)


# --- handlers ---------------------------------------------------------------


def list_boards(services: BoardListing, actor: ActorContext, args: ToolArguments) -> ToolResult:
    """The boards a worker may start from, by name; archived ones only on request."""
    actor.require("boards:read")
    status = _text(args.get("status"))
    include_archived = bool(args.get("include_archived", False)) or status == "archived"
    entries, total = services.board.list(
        q=_text(args.get("query")),
        status=status,
        sort="name",
        order="asc",
        limit=BOARD_LIST_LIMIT,
        with_counts=True,
    )
    boards: list[ToolResult] = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "description": entry["description"],
            "status": entry["status"],
            "loop_count": entry["loop_count"],
            "updated_at": entry["updated_at"],
        }
        for entry in entries
        if include_archived or entry["status"] != "archived"
    ]
    return {
        "boards": boards,
        "count": len(boards),
        "truncated": total > BOARD_LIST_LIMIT,
        "next_step": (
            "Call read_board with one of these board ids to list its Loops, or search_tickets "
            "to find a Ticket by words."
        ),
    }


def _found_ticket(hit: SearchHit, columns: Mapping[str, str]) -> ToolResult:
    return {
        "board_id": hit["board_id"],
        "loop_id": hit["loop_id"],
        "loop_key": hit["loop_key"],
        "card_id": hit["id"],
        "key": hit["ticket_key"],
        "title": hit["title"],
        "column": columns.get(hit["list_id"]),
        "completed_at": hit["completed_at"],
    }


def search_tickets(
    services: TicketSearching, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    """Tickets whose title or description carry the words: in one Loop, in a board's open Loops
    (its completed ones on request), or in the open Loops of every active board."""
    actor.require("cards:read")
    query = _require(args, "query")
    limit = _whole_number(args, "limit", default=SEARCH_DEFAULT, maximum=SEARCH_LIMIT)
    board_id = _text(args.get("board_id"))
    loop_id = _text(args.get("loop_id"))
    if loop_id is not None and board_id is None:
        raise ValidationFailure(
            "board_id is required with loop_id", details={"argument": "board_id"}
        )
    hits: list[SearchHit] = []
    engines: list[str] = []
    truncated = False
    if board_id is None:
        found = services.search.global_search(q=query, limit_per_loop=limit)
        hits = found["items"]
        engines.append(found["engine"])
    else:
        loop_ids = (
            [loop_id]
            if loop_id is not None
            else [
                entry["id"]
                for entry in services.loop.list(
                    board_id,
                    include_completed=bool(args.get("include_completed", False)),
                    include_archived=False,
                )
            ]
        )
        for current in loop_ids:
            if len(hits) >= limit:
                truncated = True
                break
            page = services.search.board(board_id, current, q=query, limit=limit)
            hits += page["items"]
            engines.append(page["engine"])
            truncated = truncated or page["has_more"]
    if len(hits) > limit:
        truncated = True
        del hits[limit:]
    # The column is the list's name, read once per Loop a hit sits in.
    columns: dict[tuple[str, str], dict[str, str]] = {}
    tickets: list[ToolResult] = []
    for hit in hits:
        place = (hit["board_id"], hit["loop_id"])
        if place not in columns:
            columns[place] = {
                entry["id"]: entry["name"]
                for entry in services.list.list(
                    hit["board_id"], hit["loop_id"], include_archived=True
                )
            }
        tickets.append(_found_ticket(hit, columns[place]))
    return {
        "query": query,
        "tickets": tickets,
        "engine": search_engine(engines),
        "truncated": truncated,
        "next_step": (
            "Call read_ticket with the board_id and card_id of a hit before you change anything."
        ),
    }


def _read_board(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("boards:read")
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    board = services.board.get(board_id)
    loops = services.loop.list(
        board_id,
        include_completed=bool(args.get("include_completed", False)),
        include_archived=False,
    )
    # Where each Loop stands, and what comes next, is loop_summaries' answer; this one names them.
    summaries: list[ToolResult] = [
        {"id": entry["id"], "key": entry["key"], "name": entry["name"], "stage": entry["stage"]}
        for entry in loops
    ]
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
            "Call loop_summaries for where each Loop stands and what comes next, list_tickets for "
            "the Tickets, or read_loop with a loop id (or key) for one Loop's overview."
        ),
    }


def allowed_actions(card: CardEntry, *, execution_allowed: bool) -> list[str]:
    """The tools a worker may call on a Ticket now. ``comment_ticket`` always, done or not, as the
    service allows (only a read-only Loop or board refuses it); ``set_ticket_wait`` while it is
    open and waits for nothing (clearing a wait is a person's act); ``complete_ticket`` only while
    the Ticket is ready (no blocker, no wait), open and not a person's, and for a planned one only
    while the Loop executes."""
    if card["archived_at"]:
        return ["comment_ticket"]
    may_wait = not card["completed_at"] and card["waiting_for"] == "nothing"
    if card["human_action_required"] and not card["completed_at"]:
        return ["comment_ticket", "ask_agents", *(["set_ticket_wait"] if may_wait else [])]
    allowed = ["comment_ticket", "assign_ticket", "move_ticket", "ask_agents"]
    if card["plan_item_id"] and not card["ready"]:
        # A planned Ticket waits for its phase entry conditions; a manual one does not.
        allowed.remove("move_ticket")
    if may_wait:
        allowed.append("set_ticket_wait")
    if card["state"] == "ready" and (execution_allowed or not card["plan_item_id"]):
        allowed.append("complete_ticket")
    return allowed


def _read_ticket(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
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
    allowed = allowed_actions(card, execution_allowed=readiness["execution_allowed"])
    return {
        "ticket": {
            "id": card["id"],
            "key": card["ticket_key"],
            "title": card["title"],
            "summary": card["summary"],
            "summary_source": card["summary_source"],
            "summary_stale": card["summary_stale"],
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
            "state": card["state"],
            "workplace": card["workplace"],
            "wait": (
                None
                if card["waiting_for"] == "nothing"
                else {
                    "waiting_for": card["waiting_for"],
                    "reason": card["waiting_reason"],
                    "set_by": card["waiting_set_by"],
                    "set_at": card["waiting_set_at"],
                }
            ),
            "blockers": card["blockers"],
            "human_action_required": card["human_action_required"],
            "needs_person": card["needs_person"],
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


__all__ = [
    "BOARD_LIST_LIMIT",
    "SEARCH_DEFAULT",
    "SEARCH_LIMIT",
    "BoardListing",
    "TicketSearching",
    "ToolArguments",
    "ToolResult",
    "_loop_lists",
    "_read_board",
    "_read_ticket",
    "_require",
    "_text",
    "_ticket_location",
    "_whole_number",
    "allowed_actions",
    "list_boards",
    "search_tickets",
]
