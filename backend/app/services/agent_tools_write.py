"""The worker tools that change something: assign, move and comment, a Loop, Info, runs, threads.

The catalogue in ``agent_tools`` declares each tool's name, description, scopes and input schema;
the handlers here run the entries that write. Each takes ``(services, actor, args)``, opens with the
``actor.require`` checks of the scopes its entry declares and calls the same services as the REST
routes, so authorization, version checks and workflow gates are the ones REST already enforces.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardMove, CardUpdate
from ..schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from ..schemas.loops import GenerationRequest, InfoRevisionWrite, LoopCreate
from ..schemas.subresources import CommentCreate
from .agent_tools_read import (
    ToolArguments,
    ToolResult,
    _loop_lists,
    _require,
    _rows,
    _text,
    _thread_view,
    _ticket_location,
)

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services
    from .lists import ListEntry

# A retried call arrives seconds later; a deliberate repeat rarely does. This window is what tells
# them apart without a shared idempotency store.
DEDUPE_WINDOW_SECONDS = 300


def _seconds_since(timestamp: str) -> float:
    """Age of an ISO 8601 timestamp in seconds; a malformed one counts as ancient."""
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(UTC) - moment).total_seconds()


def _as_int(value: JsonValue) -> int:
    """``int()`` of a JSON argument: a ``TypeError`` for nothing, a list or an object, as before."""
    if value is None or isinstance(value, (list, dict)):
        raise TypeError(f"int() argument must be a string or a number, not {type(value).__name__}")
    return int(value)


def _outcome(payload: JsonValue) -> JsonValue:
    """``(payload or {}).get("outcome")``: anything but an object raises, as reading it did."""
    document = payload or {}
    if isinstance(document, dict):
        return document.get("outcome")
    raise AttributeError(f"'{type(document).__name__}' object has no attribute 'get'")


def _resolve_list(services: Services, board_id: str, loop_id: str, wanted: str) -> ListEntry:
    """Accept a list id or its name, because a model knows columns by name, not by uuid."""
    available = _loop_lists(services, board_id, loop_id)
    for entry in available:
        if entry["id"] == wanted:
            return entry
    folded = wanted.casefold()
    for entry in available:
        if entry["name"].casefold() == folded:
            return entry
    raise ValidationFailure(
        "Unknown column",
        details={"column": wanted, "available": [entry["name"] for entry in available]},
    )


# --- handlers ---------------------------------------------------------------


def _assign_ticket(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    clear = bool(args.get("clear", False))
    assignee = _text(args.get("assignee_id"))
    if not clear and assignee is None:
        raise ValidationFailure(
            "Pass assignee_id to assign a person, or clear=true to empty the field",
            details={"argument": "assignee_id"},
        )
    loop_id, card = _ticket_location(services, board_id, card_id)
    payload = (
        CardUpdate(version=card["version"], clear_assignee=True)
        if clear
        else CardUpdate(version=card["version"], assignee_actor_id=assignee)
    )
    updated = services.card.update(actor, board_id, loop_id, card_id, payload)
    return {
        "id": updated["id"],
        "assignee": (
            {
                "id": updated["assignee_actor_id"],
                "name": updated["assignee_name"],
                "type": updated["assignee_type"],
            }
            if updated["assignee_actor_id"]
            else None
        ),
        "version": updated["version"],
    }


def _move_ticket(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    target = _require(args, "column")
    loop_id, _ = services.card.locate(board_id, card_id)
    column = _resolve_list(services, board_id, loop_id, target)
    expected = args.get("version")
    position = _as_int(args.get("position") or 0)
    attempts = 1 if expected else 2
    for attempt in range(attempts):
        card = services.card.get(board_id, loop_id, card_id)
        version = _as_int(expected) if expected else card["version"]
        try:
            moved = services.card.move(
                actor,
                board_id,
                loop_id,
                card_id,
                CardMove(version=version, list_id=column["id"], position=position),
            )
        except VersionConflict:
            if attempt + 1 >= attempts:
                raise
            continue
        return {
            "id": moved["id"],
            "key": moved["ticket_key"],
            "column": column["name"],
            "list_id": moved["list_id"],
            "version": moved["version"],
            "completed_at": moved["completed_at"],
        }
    raise NotFound("Ticket not found")  # pragma: no cover - loop returns or raises


def _comment_ticket(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("comments:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    content = _require(args, "content")
    # Resolving the Ticket proves it belongs to this board before anything is written.
    _ticket_location(services, board_id, card_id)
    for existing in services.comment.list(board_id, card_id):
        if (
            existing["actor_id"] == actor.actor_id
            and existing["content"] == content
            and _seconds_since(existing["created_at"]) < DEDUPE_WINDOW_SECONDS
        ):
            return {
                "id": existing["id"],
                "actor": existing["actor_name"],
                "content": existing["content"],
                "created_at": existing["created_at"],
                "deduplicated": True,
            }
    created = services.comment.create(
        actor, board_id, card_id, CommentCreate(content=content)
    )
    return {
        "id": created["id"],
        "actor": created["actor_name"],
        "content": created["content"],
        "created_at": created["created_at"],
    }


def _create_loop(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:write")
    board_id = _require(args, "board_id")
    name = _require(args, "name")
    columns = args.get("columns")
    payload = LoopCreate(
        name=name,
        goal=_text(args.get("goal")) or "",
        column_names=[str(entry) for entry in columns]
        if isinstance(columns, list) and columns
        else None,
    )
    loop, _ = services.loop.create(
        actor,
        board_id,
        payload,
        idempotency_key=_text(args.get("idempotency_key")),
    )
    return {
        "loop": {
            "id": loop["id"],
            "key": loop["key"],
            "name": loop["name"],
            "stage": loop["stage"],
        },
        "next_step": (
            "Call write_info with this loop_id and the agreed intent, then run_analysis."
        ),
    }


def _write_info(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:write")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    content = _require(args, "content")
    current = services.loop_document.documents(board_id, loop_id)["documents"]["info"]
    if current["current_content"] == content:
        return {
            "loop_id": loop_id,
            "revision_number": current["current_revision_number"],
            "revision_id": current["current_revision_id"],
            "state": current["state"],
            "deduplicated": True,
            "next_step": "Call run_analysis to have an agent turn this Info into findings.",
        }
    documents = services.loop_document.save_info(
        actor,
        board_id,
        loop_id,
        InfoRevisionWrite(
            content=content,
            note=_text(args.get("note")) or "",
            expected_revision_id=_text(args.get("expected_revision_id")),
        ),
    )
    info = documents["documents"]["info"]
    return {
        "loop_id": loop_id,
        "revision_number": info["current_revision_number"],
        "revision_id": info["current_revision_id"],
        "state": info["state"],
        "next_step": "Call run_analysis to have an agent turn this Info into findings.",
    }


def _run_analysis(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    run, _ = services.loop_generation.start(
        actor,
        board_id,
        loop_id,
        GenerationRequest(
            purpose="analysis",
            agent_id=_text(args.get("agent_id")),
            instructions=_text(args.get("instructions")) or "",
        ),
    )
    run_id = str(run["id"])
    wait = max(0, min(_as_int(args.get("wait_seconds") or 0), 120))
    deadline = time.monotonic() + wait
    while wait and run["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.5)
        run = services.loop_generation.get(board_id, loop_id, run_id)
    documents = services.loop_document.documents(board_id, loop_id)
    analysis = documents["documents"]["analysis_ai"]
    # A completed analysis is written for people by a run of its own (loop_generation), listed
    # before this one because it started after it.
    human: dict[str, object] | None = None
    for entry in services.loop_generation.list_runs(board_id, loop_id, limit=10):
        if entry.get("id") == run_id:
            break
        if entry.get("purpose") == "analysis_human":
            human = entry
            break
    return {
        "human_view": (
            {"run_id": human.get("id"), "status": human.get("status")} if human else None
        ),
        "run": {
            "id": run_id,
            "status": run["status"],
            "error_code": run.get("error_code"),
            "error_message": run.get("error_message"),
            "agent": run.get("agent_name"),
        },
        "analysis": {
            "state": analysis["state"],
            "revision_number": analysis["current_revision_number"],
            "revision_id": analysis["current_revision_id"],
            "summary": _outcome(analysis.get("current_payload")),
        },
        "next_step": (
            "The analysis is a candidate: a person reviews and approves it. Read it with "
            "read_loop, or poll this tool again with the same loop_id."
        ),
    }


def _run_roadmap(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("loops:generate")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    run, _ = services.loop_generation.start(
        actor,
        board_id,
        loop_id,
        GenerationRequest(
            purpose="roadmap",
            agent_id=_text(args.get("agent_id")),
            instructions=_text(args.get("instructions")) or "",
        ),
    )
    run_id = str(run["id"])
    wait = max(0, min(_as_int(args.get("wait_seconds") or 0), 120))
    deadline = time.monotonic() + wait
    while wait and run["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.5)
        run = services.loop_generation.get(board_id, loop_id, run_id)
    documents = services.loop_document.documents(board_id, loop_id)
    roadmap = documents["documents"]["roadmap_ai"]
    return {
        "run": {
            "id": run_id,
            "status": run["status"],
            "error_code": run.get("error_code"),
            "error_message": run.get("error_message"),
            "agent": run.get("agent_name"),
        },
        "roadmap": {
            "state": roadmap["state"],
            "revision_number": roadmap["current_revision_number"],
            "revision_id": roadmap["current_revision_id"],
        },
        "next_step": (
            "The RoadMap is a candidate: a person approves it, and that approval publishes the "
            "Tickets. Read it with read_loop."
        ),
    }


def _reply_discussion(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    content = _require(args, "content")
    detail = services.discussion.add_message(
        actor,
        board_id,
        discussion_id,
        DiscussionMessageCreate(
            content=content, parent_message_id=_text(args.get("parent_message_id"))
        ),
    )
    run: Mapping[str, object] | None = None
    if bool(args.get("run", True)) and detail["status"] not in {"closed", "decided"}:
        try:
            run = services.run.start(
                actor, board_id, discussion_id, rounds=1, autonomous=False
            )
        except Conflict as error:
            # A run already active is not a failure: the message is posted and the caller can poll.
            run = {"status": "running", "stop_reason": error.code}
    thread = services.discussion.get(board_id, discussion_id)
    view = _thread_view(thread)
    view["run"] = (
        {
            "id": run.get("run_id"),
            "status": run.get("run_status") or run.get("status"),
            "stop_reason": run.get("stop_reason"),
        }
        if run
        else None
    )
    return view


def _ask_agents(
    services: Services, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    question = _require(args, "question")
    requested = args.get("agent_ids")
    if isinstance(requested, list) and requested:
        participants = [str(entry) for entry in requested]
    else:
        participants = [entry["id"] for entry in services.agent.askable_agents(board_id)]
    if not participants:
        raise ValidationFailure(
            "No agent can answer on this board. Add one in Settings -> Agents and select it on "
            "the board.",
            code="no_agents_available",
        )
    recent = [
        *services.discussion.list(board_id, status="open", limit=50),
        *services.discussion.list(board_id, status="discussing", limit=50),
    ]
    for existing in recent:
        if (
            existing.get("card_id") == card_id
            and existing.get("goal") == question
            and existing.get("created_by_actor_id") == actor.actor_id
            and _seconds_since(str(existing["created_at"])) < DEDUPE_WINDOW_SECONDS
        ):
            view = _thread_view(services.discussion.get(board_id, str(existing["id"])))
            view["deduplicated"] = True
            return view
    rounds = args.get("rounds")
    thread = services.discussion.create(
        actor,
        board_id,
        DiscussionCreate(
            card_id=card_id,
            goal=question,
            mode="roundtable",
            participant_ids=participants[:12],
            max_rounds=_as_int(rounds or 1),
        ),
    )
    run = services.run.start(actor, board_id, str(thread["id"]), rounds=1, autonomous=False)
    thread = services.discussion.get(board_id, str(thread["id"]))
    return {
        "discussion_id": thread["id"],
        "title": thread["title"],
        "status": thread["status"],
        "run": {
            "id": run.get("run_id"),
            "status": run.get("run_status"),
            "stop_reason": run.get("stop_reason"),
            "answers": run.get("answers"),
            "failures": run.get("failures") or [],
        },
        "messages": [
            {
                "author": message["author_name"],
                "author_type": message["author_type"],
                "content": message["content"],
            }
            for message in _rows(thread["messages"])
        ],
        "positions": [
            {
                "agent": vote["display_name"],
                "position": vote["position"],
                "justification": vote["justification"],
            }
            for vote in _rows(thread.get("votes", []))
        ],
    }


__all__ = [
    "DEDUPE_WINDOW_SECONDS",
    "_ask_agents",
    "_assign_ticket",
    "_comment_ticket",
    "_create_loop",
    "_move_ticket",
    "_reply_discussion",
    "_resolve_list",
    "_run_analysis",
    "_run_roadmap",
    "_seconds_since",
    "_write_info",
]
