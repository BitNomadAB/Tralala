"""One curated catalogue of what an external worker may do against a Board.

The catalogue is the single description of the worker surface. ``/mcp`` serves it as MCP tools and
``/llms.txt`` summarises it for anyone who only speaks REST. The browser WebMCP adapter is a
separate, UI-contextual surface for a person's own browser session; unifying it on this catalogue is
deliberately left for later. Every handler calls the same services as the REST routes, so
authorization, version checks and workflow gates are exactly the ones REST already enforces — a tool
can be narrower than a scope, never wider.

Deliberately absent: board and list structure changes, Ticket creation, archiving and every human
decision. A worker agrees an intent, creates the Loop, writes the Info while it is still
speculative, asks for the Analysis and tracks the Tickets; a person still approves the analysis and
the RoadMap, confirms human work and accepts QA.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..core.context import ActorContext
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailure, VersionConflict
from ..schemas.cards import CardMove, CardUpdate
from ..schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from ..schemas.loops import GenerationRequest, InfoRevisionWrite, LoopCreate
from ..schemas.subresources import CommentCreate

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services
    from .cards import CardEntry
    from .lists import ListEntry

# A retried call arrives seconds later; a deliberate repeat rarely does. This window is what tells
# them apart without a shared idempotency store.
DEDUPE_WINDOW_SECONDS = 300


@dataclass(frozen=True, slots=True)
class AgentTool:
    """One callable capability: wire contract plus the handler that runs it."""

    name: str
    description: str
    scopes: tuple[str, ...]
    input_schema: dict[str, Any]
    handler: Callable[[Services, ActorContext, dict[str, Any]], dict[str, Any]]


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _object(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _seconds_since(timestamp: str) -> float:
    """Age of an ISO 8601 timestamp in seconds; a malformed one counts as ancient."""
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(UTC) - moment).total_seconds()


def _require(args: dict[str, Any], key: str) -> str:
    value = _text(args.get(key))
    if value is None:
        raise ValidationFailure(f"{key} is required", details={"argument": key})
    return value


def _loop_lists(services: Services, board_id: str, loop_id: str) -> list[ListEntry]:
    return services.list.list(board_id, loop_id)


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


def _ticket_location(
    services: Services, board_id: str, card_id: str
) -> tuple[str, CardEntry]:
    loop_id, _ = services.card.locate(board_id, card_id)
    return loop_id, services.card.get(board_id, loop_id, card_id)


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


def _assign_ticket(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("cards:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    target = _require(args, "column")
    loop_id, _ = services.card.locate(board_id, card_id)
    column = _resolve_list(services, board_id, loop_id, target)
    expected = args.get("version")
    position = int(args.get("position") or 0)
    attempts = 1 if expected else 2
    for attempt in range(attempts):
        card = services.card.get(board_id, loop_id, card_id)
        version = int(expected) if expected else card["version"]
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    wait = max(0, min(int(args.get("wait_seconds") or 0), 120))
    deadline = time.monotonic() + wait
    while wait and run["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.5)
        run = services.loop_generation.get(board_id, loop_id, run_id)
    documents = services.loop_document.documents(board_id, loop_id)
    analysis = documents["documents"]["analysis_ai"]
    return {
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
            "summary": (analysis.get("current_payload") or {}).get("outcome"),
        },
        "next_step": (
            "The analysis is a candidate: a person reviews and approves it. Read it with "
            "read_loop, or poll this tool again with the same loop_id."
        ),
    }


def _run_roadmap(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    wait = max(0, min(int(args.get("wait_seconds") or 0), 120))
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


def _read_discussion(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
    actor.require("discussions:read")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    return _thread_view(services.discussion.get(board_id, discussion_id))


def _reply_discussion(
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
    run: dict[str, Any] | None = None
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
    services: Services, actor: ActorContext, args: dict[str, Any]
) -> dict[str, Any]:
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
            and _seconds_since(existing["created_at"]) < DEDUPE_WINDOW_SECONDS
        ):
            view = _thread_view(services.discussion.get(board_id, existing["id"]))
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
            max_rounds=int(rounds or 1),
        ),
    )
    run = services.run.start(actor, board_id, thread["id"], rounds=1, autonomous=False)
    thread = services.discussion.get(board_id, thread["id"])
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
            for message in thread["messages"]
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


_BOARD_ID = _string("Board identifier from read_board")
_CARD_ID = _string("Ticket identifier from read_board or read_loop")


def tool_catalog() -> dict[str, AgentTool]:
    """The worker surface: how to read a task, start one, track it and ask for advice."""
    tools = [
        AgentTool(
            name="read_board",
            description=(
                "List the Loops of a board with their stage, whether execution is allowed, the "
                "people you can assign, and the agents you can ask. Start here."
            ),
            scopes=("boards:read", "loops:read"),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "include_completed": {
                        "type": "boolean",
                        "description": "Also list Loops that are already completed",
                    },
                },
                required=["board_id"],
            ),
            handler=_read_board,
        ),
        AgentTool(
            name="read_loop",
            description=(
                "Read one Loop: its goal, the Info/Analysis/RoadMap documents, the plan with "
                "phase and Ticket readiness, and the Kanban columns. Use this to understand the "
                "task before touching a Ticket."
            ),
            scopes=("loops:read",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier from read_board"),
                    "document_kinds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Limit the documents, for example [\"info\"]",
                    },
                },
                required=["board_id", "loop_id"],
            ),
            handler=_read_loop,
        ),
        AgentTool(
            name="read_ticket",
            description=(
                "Read one Ticket with acceptance criteria, evidence, checklist, comments, "
                "current column, version and the actions that are allowed right now."
            ),
            scopes=("cards:read",),
            input_schema=_object(
                {"board_id": _BOARD_ID, "card_id": _CARD_ID},
                required=["board_id", "card_id"],
            ),
            handler=_read_ticket,
        ),
        AgentTool(
            name="assign_ticket",
            description=(
                "Set or clear the owner of a Ticket. Use a person id from read_board; the "
                "Ticket's current version is read for you."
            ),
            scopes=("cards:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "assignee_id": _string("Person id from read_board"),
                    "clear": {
                        "type": "boolean",
                        "description": "Remove the current assignee instead of setting one",
                    },
                },
                required=["board_id", "card_id"],
            ),
            handler=_assign_ticket,
        ),
        AgentTool(
            name="move_ticket",
            description=(
                "Move a Ticket to another Kanban column of its Loop. Accepts the column id or "
                "its name, and reads the Ticket version for you; omit version unless you need "
                "strict optimistic concurrency."
            ),
            scopes=("cards:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "column": _string("Target column id or name, for example \"In progress\""),
                    "position": {"type": "number", "minimum": 0},
                    "version": {"type": "number", "minimum": 1},
                },
                required=["board_id", "card_id", "column"],
            ),
            handler=_move_ticket,
        ),
        AgentTool(
            name="comment_ticket",
            description="Add a comment to a Ticket: progress, findings or a blocker.",
            scopes=("comments:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "content": _string("Markdown comment"),
                },
                required=["board_id", "card_id", "content"],
            ),
            handler=_comment_ticket,
        ),
        AgentTool(
            name="create_loop",
            description=(
                "Create a Loop on a board: the place where one coherent change is planned and "
                "tracked. Columns default to the board's Loop columns."
            ),
            scopes=("loops:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "name": _string("Name of the change, for example \"Account enrolment\""),
                    "goal": _string("One sentence on the outcome"),
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Kanban column names, in order",
                    },
                    "idempotency_key": _string(
                        "Send the same key when you retry, so a timeout cannot create a second Loop"
                    ),
                },
                required=["board_id", "name"],
            ),
            handler=_create_loop,
        ),
        AgentTool(
            name="write_info",
            description=(
                "Write the Loop's Info: requirements, constraints and the desired outcome. Allowed "
                "while the Loop is still draft or under analysis review; once planning has started "
                "the edit belongs to a signed-in person."
            ),
            scopes=("loops:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier from read_board or create_loop"),
                    "content": _string(
                        "Markdown: what we want, what constrains us, what is out of scope"
                    ),
                    "note": _string("Optional short note recorded with the revision"),
                    "expected_revision_id": _string(
                        "Optional current Info revision id; a mismatch returns document_stale"
                    ),
                },
                required=["board_id", "loop_id", "content"],
            ),
            handler=_write_info,
        ),
        AgentTool(
            name="run_analysis",
            description=(
                "Ask a board agent for the Analysis candidate of a Loop that has Info. Returns the "
                "generation run and the state of the analysis; the candidate is approved by a "
                "person, never by an agent."
            ),
            scopes=("loops:generate",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier"),
                    "agent_id": _string("Optional agent to run; defaults to the Loop's choice"),
                    "instructions": _string("Optional extra direction for this run"),
                    "wait_seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 120,
                        "description": "Poll the run for up to this long before returning",
                    },
                },
                required=["board_id", "loop_id"],
            ),
            handler=_run_analysis,
        ),
        AgentTool(
            name="run_roadmap",
            description=(
                "Ask a board agent for the RoadMap candidate of a Loop whose analysis is approved. "
                "Approving the RoadMap is a person's decision and publishes the Tickets."
            ),
            scopes=("loops:generate",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier"),
                    "agent_id": _string("Optional agent to run; defaults to the Loop's choice"),
                    "instructions": _string("Optional extra direction for this run"),
                    "wait_seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 120,
                        "description": "Poll the run for up to this long before returning",
                    },
                },
                required=["board_id", "loop_id"],
            ),
            handler=_run_roadmap,
        ),
        AgentTool(
            name="ask_agents",
            description=(
                "Ask the local agents a question about one Ticket and read their answers. They "
                "read and advise; they never change the Ticket."
            ),
            scopes=("discussions:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "question": _string("What you need answered"),
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Ask only these agents; omit to ask every agent on the board"
                        ),
                    },
                    "rounds": {"type": "number", "minimum": 1, "maximum": 4},
                },
                required=["board_id", "card_id", "question"],
            ),
            handler=_ask_agents,
        ),
        AgentTool(
            name="read_discussion",
            description=(
                "Read one discussion thread with its messages and each agent's position. Use it "
                "after ask_agents to re-read answers, or before replying."
            ),
            scopes=("discussions:read",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "discussion_id": _string("Discussion identifier from ask_agents"),
                },
                required=["board_id", "discussion_id"],
            ),
            handler=_read_discussion,
        ),
        AgentTool(
            name="reply_discussion",
            description=(
                "Post a follow-up in an existing thread and, unless run is false, let the agents "
                "answer it in the same thread. This is how a question becomes a conversation."
            ),
            scopes=("discussions:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "discussion_id": _string("Discussion identifier from ask_agents"),
                    "content": _string("Your follow-up question or finding"),
                    "parent_message_id": _string("Optional message being answered"),
                    "run": {
                        "type": "boolean",
                        "description": "Start one answering round; defaults to true",
                    },
                },
                required=["board_id", "discussion_id", "content"],
            ),
            handler=_reply_discussion,
        ),
    ]
    return {tool.name: tool for tool in tools}


def missing_scopes(tool: AgentTool, actor: ActorContext) -> tuple[str, ...]:
    """Scopes the tool needs that the actor does not hold; empty means it may run."""
    return tuple(scope for scope in tool.scopes if not actor.has_scope(scope))


def describe_scope(tool: AgentTool) -> str:
    return "Requires " + ", ".join(f"`{scope}`" for scope in tool.scopes) + "."


def run_tool(
    services: Services, actor: ActorContext, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Run one catalogue entry as the calling actor.

    ``Forbidden`` for a missing scope is raised before the handler, so a tool never becomes an
    implicit privilege escalation.
    """
    tool = tool_catalog().get(name)
    if tool is None:
        raise NotFound("Unknown tool", code="unknown_tool", details={"tool": name})
    missing = missing_scopes(tool, actor)
    if missing:
        raise Forbidden(
            "Missing required scope: " + ", ".join(missing),
            details={"required_scopes": list(missing)},
        )
    return tool.handler(services, actor, args or {})


__all__ = ["AgentTool", "describe_scope", "missing_scopes", "run_tool", "tool_catalog"]
