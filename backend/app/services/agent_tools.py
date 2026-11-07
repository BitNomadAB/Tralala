"""One curated catalogue of what an external worker may do against a Board.

The catalogue is the single description of the worker surface. ``/mcp`` serves it as MCP tools and
``/llms.txt`` summarises it for anyone who only speaks REST. The browser WebMCP adapter is a
separate, UI-contextual surface for a person's own browser session; unifying it on this catalogue is
deliberately left for later. Every handler calls the same services as the REST routes, so
authorization, version checks and workflow gates are exactly the ones REST already enforces — a tool
can be narrower than a scope, never wider.

Deliberately absent: board and list structure changes, planned Ticket creation, archiving and every
human decision. A worker lists the boards and finds its Ticket, agrees an intent, creates the Loop,
writes the Info while it is still speculative, writes its own analysis and RoadMap (or asks a board
agent for them), tracks and completes the Tickets and adds the follow-ups it finds outside the plan;
a person still approves the analysis and the RoadMap, confirms human work and accepts QA.

The handlers live beside this module, in ``agent_tools_read``, ``agent_tools_write``,
``agent_tools_tickets``, ``agent_tools_work``, ``agent_tools_plan`` and
``agent_tools_discussions``, among others, and the argument schemas in ``agent_tools_schema``;
this module holds the catalogue and the dispatch and re-exports them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.context import ActorContext
from ..core.errors import Forbidden, NotFound
from .agent_tools_discussions import ask_agents, read_discussion, reply_discussion
from .agent_tools_documents import document_tools, read_document, read_loop
from .agent_tools_identity import identity_tools, whoami
from .agent_tools_listing import list_tickets, listing_tools, write_ticket_summaries
from .agent_tools_loops import loop_summaries, loop_tools
from .agent_tools_notes import read_notes, write_note
from .agent_tools_plan import map_plan_ids, plan_tools, write_analysis, write_brief, write_roadmap
from .agent_tools_read import (
    ToolArguments,
    ToolResult,
    _read_board,
    _read_ticket,
    allowed_actions,
    list_boards,
    search_tickets,
)
from .agent_tools_schema import (
    AgentTool,
    ArgumentSchema,
    InputSchema,
    describe_scope,
    missing_scopes,
)
from .agent_tools_schema import object_schema as _object
from .agent_tools_schema import string_argument as _string
from .agent_tools_tickets import comment_ticket, complete_ticket, create_ticket
from .agent_tools_work import set_ticket_wait, work_tools
from .agent_tools_write import (
    _assign_ticket,
    _create_loop,
    _move_ticket,
    _run_analysis,
    _run_roadmap,
    _write_info,
)

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from . import Services


_BOARD_ID = _string("Board identifier from list_boards")
_CARD_ID = _string("Ticket identifier from list_tickets or search_tickets")
_LOOP_ID = _string("Loop identifier from read_board")
_LOOP_REF = _string("Loop id or key (AN001), from loop_summaries or read_board")
_INCLUDE_PROSE: ArgumentSchema = {
    "type": "boolean",
    "description": "Also return the prose of every structured answer; defaults to false",
}


def _run_arguments() -> InputSchema:
    """What run_analysis and run_roadmap take: a Loop, and optionally an agent and a wait."""
    return _object(
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
    )


def tool_catalog() -> dict[str, AgentTool]:
    """The worker surface: how to find a task, read it, start one, track it and ask for advice."""
    write_analysis_tool, write_roadmap_tool, write_brief_tool = plan_tools(_BOARD_ID)
    tools = [
        *identity_tools(),
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
        *loop_tools(_BOARD_ID),
        AgentTool(
            name="read_board",
            description=(
                "Name a board's Loops (id, key, name and stage), the people you can assign and "
                "the agents you can ask. Where each Loop stands is loop_summaries."
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
        *document_tools(_BOARD_ID, _LOOP_REF),
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
        *listing_tools(_BOARD_ID),
        *work_tools(_BOARD_ID, _CARD_ID),
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
            name="create_ticket",
            description=(
                "Add a follow-up you found while executing a Loop: a Ticket outside the plan, "
                "keyed <LoopKey>-UNP-<nnn>, in the first column. It never blocks the plan or the "
                "Loop's completion. With follow_up_of, the origin Ticket gets a comment pointing "
                "at it. Asking for the same Ticket again answers the first one."
            ),
            scopes=("cards:write", "comments:write"),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _string("Loop identifier from read_board"),
                    "title": _string("Short title of the work"),
                    "description": _string("Markdown: what was found and what is to be done"),
                    "summary": _string("Optional: what it is about in a sentence or two"),
                    "follow_up_of": _string("Optional id of the Ticket this work came out of"),
                    "priority": _string("Optional: none, low, medium, high or urgent"),
                    "workplace": _string("Optional: codebase, outside or unknown (the default)"),
                    "waiting_for": _string(
                        "Optional: nothing (the default), decision, information, access or "
                        "third_party; a wait needs waiting_reason"
                    ),
                    "waiting_reason": _string("What the wait needs, at most 500 characters"),
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional area labels by the names the board has",
                    },
                },
                required=["board_id", "loop_id", "title"],
            ),
            handler=create_ticket,
        ),
        AgentTool(
            name="comment_ticket",
            description=(
                "Add a comment to a Ticket, done or not, in a completed Loop too: progress, "
                "findings, a blocker, or a note on later work such as the Loop that replaced it."
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
            name="write_note",
            description=(
                "Add a note to a Loop's log: what belongs to the Loop and to no single Ticket, "
                "such as the baseline, the checks that passed, a merge, a deploy or what is still "
                "open. Notes are kept in order and never edited."
            ),
            scopes=("loops:write",),
            input_schema=_object(
                {"board_id": _BOARD_ID, "loop_id": _LOOP_ID, "content": _string("Markdown")},
                required=["board_id", "loop_id", "content"],
            ),
            handler=write_note,
        ),
        AgentTool(
            name="read_notes",
            description=(
                "Read a Loop's notes, oldest first: the newest page, or the one before a note."
            ),
            scopes=("loops:read",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "loop_id": _LOOP_ID,
                    "limit": {"type": "number", "minimum": 1, "maximum": 200},
                    "before": _string("Optional note id; the answer's older value"),
                },
                required=["board_id", "loop_id"],
            ),
            handler=read_notes,
        ),
        AgentTool(
            name="run_analysis",
            description=(
                "Ask a board agent for the Analysis candidate of a Loop that has Info. Returns the "
                "generation run and the state of the analysis; the candidate is approved by a "
                "person, never by an agent."
            ),
            scopes=("loops:generate",),
            input_schema=_run_arguments(),
            handler=_run_analysis,
        ),
        write_analysis_tool,
        AgentTool(
            name="run_roadmap",
            description=(
                "Ask a board agent for the RoadMap candidate of a Loop whose analysis is approved. "
                "Approving the RoadMap is a person's decision and publishes the Tickets."
            ),
            scopes=("loops:generate",),
            input_schema=_run_arguments(),
            handler=_run_roadmap,
        ),
        write_roadmap_tool,
        write_brief_tool,
        AgentTool(
            name="ask_agents",
            description=(
                "Ask the local agents a question about one Ticket and read their answers: each "
                "agent's position (yes, yes_with_conditions, no, unclear) with its recommendation, "
                "reasons and conditions, and Tralala's synthesis of the round. They read and "
                "advise; they never change the Ticket, and a person decides."
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
                    "include_prose": _INCLUDE_PROSE,
                },
                required=["board_id", "card_id", "question"],
            ),
            handler=ask_agents,
        ),
        AgentTool(
            name="read_discussion",
            description=(
                "Read one discussion thread: Tralala's synthesis of the newest round (a "
                "suggestion, never a decision), each agent's current position and the messages "
                "with their structured answers. Use it after ask_agents, or before replying."
            ),
            scopes=("discussions:read",),
            input_schema=_object(
                {
                    "board_id": _BOARD_ID,
                    "discussion_id": _string("Discussion identifier from ask_agents"),
                    "include_prose": _INCLUDE_PROSE,
                },
                required=["board_id", "discussion_id"],
            ),
            handler=read_discussion,
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
                    "include_prose": _INCLUDE_PROSE,
                },
                required=["board_id", "discussion_id", "content"],
            ),
            handler=reply_discussion,
        ),
    ]
    return {tool.name: tool for tool in tools}


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
    "AgentTool",
    "ArgumentSchema",
    "InputSchema",
    "ToolArguments",
    "ToolResult",
    "_assign_ticket",
    "_create_loop",
    "_move_ticket",
    "_read_board",
    "_read_ticket",
    "_run_analysis",
    "_run_roadmap",
    "_write_info",
    "allowed_actions",
    "ask_agents",
    "comment_ticket",
    "complete_ticket",
    "create_ticket",
    "describe_scope",
    "list_boards",
    "list_tickets",
    "loop_summaries",
    "map_plan_ids",
    "missing_scopes",
    "read_discussion",
    "read_document",
    "read_loop",
    "read_notes",
    "reply_discussion",
    "run_tool",
    "search_tickets",
    "set_ticket_wait",
    "tool_catalog",
    "whoami",
    "write_analysis",
    "write_brief",
    "write_note",
    "write_roadmap",
    "write_ticket_summaries",
]
