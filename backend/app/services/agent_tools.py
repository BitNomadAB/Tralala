"""One curated catalogue of what an external worker may do against a Board.

The catalogue is the single description of the worker surface. ``/mcp`` serves it as MCP tools and
``/llms.txt`` summarises it for anyone who only speaks REST. The browser WebMCP adapter is a
separate, UI-contextual surface for a person's own browser session; unifying it on this catalogue is
deliberately left for later. Every handler calls the same services as the REST routes, so
authorization, version checks and workflow gates are exactly the ones REST already enforces — a tool
can be narrower than a scope, never wider.

Deliberately absent: board and list structure changes, Ticket creation, archiving and every human
decision. A worker lists the boards and finds its Ticket, agrees an intent, creates the Loop, writes
the Info while it is still speculative, writes its own analysis and RoadMap (or asks a board agent
for them) and tracks the Tickets; a person still approves the analysis and the RoadMap, confirms
human work and accepts QA.

The handlers live beside this module, in ``agent_tools_read``, ``agent_tools_write``,
``agent_tools_tickets`` and ``agent_tools_plan``, and the argument schemas in
``agent_tools_schema``; this module holds the catalogue and the dispatch and re-exports them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.context import ActorContext
from ..core.errors import Forbidden, NotFound
from ..schemas.loops import AnalysisPayload, PlanPayload
from .agent_tools_plan import map_plan_ids, write_analysis, write_roadmap
from .agent_tools_read import (
    ToolArguments,
    ToolResult,
    _loop_lists,
    _read_board,
    _read_discussion,
    _read_loop,
    _read_ticket,
    _require,
    _text,
    _thread_view,
    _ticket_location,
    allowed_actions,
    list_boards,
    search_tickets,
)
from .agent_tools_schema import ArgumentSchema, InputSchema
from .agent_tools_schema import model_argument as _model
from .agent_tools_schema import object_schema as _object
from .agent_tools_schema import string_argument as _string
from .agent_tools_tickets import comment_ticket, complete_ticket
from .agent_tools_write import (
    DEDUPE_WINDOW_SECONDS,
    _ask_agents,
    _assign_ticket,
    _create_loop,
    _move_ticket,
    _reply_discussion,
    _resolve_list,
    _run_analysis,
    _run_roadmap,
    _seconds_since,
    _write_info,
)

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services


@dataclass(frozen=True, slots=True)
class AgentTool:
    """One callable capability: wire contract plus the handler that runs it."""

    name: str
    description: str
    scopes: tuple[str, ...]
    input_schema: InputSchema
    handler: Callable[[Services, ActorContext, ToolArguments], ToolResult]


_BOARD_ID = _string("Board identifier from list_boards")
_CARD_ID = _string("Ticket identifier from read_loop or search_tickets")


def tool_catalog() -> dict[str, AgentTool]:
    """The worker surface: how to find a task, read it, start one, track it and ask for advice."""
    analysis, analysis_definitions = _model(
        AnalysisPayload,
        "The analysis as one JSON object, written in the order of its fields: outcome, "
        "scope, findings with technical_detail and plain_language, recommendation and the rest",
    )
    plan, plan_definitions = _model(
        PlanPayload,
        "The RoadMap as one JSON object: a summary and the Phases in order with their Tickets; "
        "a Ticket a person must do has required_actor human, a reason and instructions",
    )
    tools = [
        AgentTool(
            name="list_boards",
            description=(
                "List the boards you may read, by name, with their status and Loop count. Start "
                "here: a board id comes from this list, never from a prompt or a guess."
            ),
            scopes=("boards:read",),
            input_schema=_object(
                {
                    "query": _string("Optional text in the board's name or description"),
                    "status": _string(
                        "Optional: active, archived, maintenance, error or migration_failed"
                    ),
                    "include_archived": {
                        "type": "boolean",
                        "description": "Also list archived boards; off unless status is archived",
                    },
                }
            ),
            handler=list_boards,
        ),
        AgentTool(
            name="read_board",
            description=(
                "List the Loops of a board with their stage, whether execution is allowed, the "
                "people you can assign, and the agents you can ask."
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
                "phase and Ticket readiness, the Kanban columns and the Tickets. Use this to "
                "understand the task before touching a Ticket."
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
            name="search_tickets",
            description=(
                "Find Tickets by words in their title or description: in one Loop, in a board's "
                "open Loops, or across every active board. Each hit names its board, Loop, key "
                "and column."
            ),
            scopes=("cards:read",),
            input_schema=_object(
                {
                    "query": _string("The words to look for"),
                    "board_id": _string("Optional: only this board"),
                    "loop_id": _string("Optional: only this Loop; needs board_id"),
                    "include_completed": {
                        "type": "boolean",
                        "description": "With board_id alone: also search its completed Loops",
                    },
                    "limit": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "At most this many hits; 25 unless given",
                    },
                },
                required=["query"],
            ),
            handler=search_tickets,
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
            description=(
                "Add a comment to a Ticket, done or not: progress, findings, a blocker, or a "
                "note on later work."
            ),
            scopes=("comments:write",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "content": _string("Markdown comment"),
                },
                required=["board_id", "card_id", "content"],
            ),
            handler=comment_ticket,
        ),
        AgentTool(
            name="complete_ticket",
            description=(
                "Finish a Ticket: marks it completed and comments your summary and evidence. This "
                "is the only way a Ticket is done; a column named Done completes nothing. The "
                "summary is kept as a comment even when the Ticket is already done or the "
                "completion is refused (human-only, blocked), and the refusal says why."
            ),
            scopes=("cards:write", "comments:write"),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "card_id": _CARD_ID,
                    "summary": _string("Markdown: what was done and how it meets the criteria"),
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional proof, one item each: a commit, a test, a link",
                    },
                },
                required=["board_id", "card_id", "summary"],
            ),
            handler=complete_ticket,
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
            name="write_analysis",
            description=(
                "Hand in your own analysis of a Loop that has Info, in Tralala's structure: the "
                "same schema, validation, rendering and review as an analysis a board agent "
                "writes. technical_detail is for engineers; plain_language is for a project "
                "manager and every risk, blocker, legal, security or question finding needs it. "
                "A person approves it; an approved analysis is replaced only after that person "
                "requests changes or resets it."
            ),
            scopes=("loops:generate",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier from read_board or create_loop"),
                    "analysis": analysis,
                    "expected_info_revision_id": _string(
                        "Optional Info revision id you wrote from (read_loop); a mismatch returns "
                        "document_stale"
                    ),
                },
                required=["board_id", "loop_id", "analysis"],
                definitions=analysis_definitions,
            ),
            handler=write_analysis,
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
            name="write_roadmap",
            description=(
                "Hand in your own RoadMap for a Loop whose analysis is approved: the Phases in "
                "order with their Tickets, in the same schema, validation and review as a "
                "generated RoadMap. Ids may be short (p1, t1): they become stable UUIDs, listed "
                "in id_map, so the same ids keep the same Tickets when you hand it in again. A "
                "person approves it, and the approval publishes the Tickets with their keys."
            ),
            scopes=("loops:generate",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier from read_board or create_loop"),
                    "plan": plan,
                    "expected_analysis_revision_id": _string(
                        "Optional technical analysis (analysis_ai) revision id you planned from; "
                        "a mismatch returns document_stale"
                    ),
                },
                required=["board_id", "loop_id", "plan"],
                definitions=plan_definitions,
            ),
            handler=write_roadmap,
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
    services: Services, actor: ActorContext, name: str, args: ToolArguments
) -> ToolResult:
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


__all__ = [
    "DEDUPE_WINDOW_SECONDS",
    "AgentTool",
    "ArgumentSchema",
    "InputSchema",
    "ToolArguments",
    "ToolResult",
    "_ask_agents",
    "_assign_ticket",
    "_create_loop",
    "_loop_lists",
    "_move_ticket",
    "_read_board",
    "_read_discussion",
    "_read_loop",
    "_read_ticket",
    "_reply_discussion",
    "_require",
    "_resolve_list",
    "_run_analysis",
    "_run_roadmap",
    "_seconds_since",
    "_text",
    "_thread_view",
    "_ticket_location",
    "_write_info",
    "allowed_actions",
    "comment_ticket",
    "complete_ticket",
    "describe_scope",
    "list_boards",
    "map_plan_ids",
    "missing_scopes",
    "run_tool",
    "search_tickets",
    "tool_catalog",
    "write_analysis",
    "write_roadmap",
]
