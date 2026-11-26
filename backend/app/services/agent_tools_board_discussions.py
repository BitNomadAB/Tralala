"""The worker tools for discussions on the board itself: open one, find them, close and reopen.

A discussion on the board has a title and no Ticket. People and several keys ask each other things
there (status, who touches what), with or without the board's local agents: ``open_discussion``
opens one addressed to nobody in particular, with no local agent and no round, and anyone answers
with ``reply_discussion``. ``list_discussions`` finds the board's threads by where they live, their
state, what is new for the caller and who opened them, never with a message's text. The one who
opened a thread closes it (``close_discussion``); the opener or a signed-in person opens it again
(``reopen_discussion``), and the service refuses anyone else (``403 not_opener``).

Each handler is public and typed on the attribute of the composition root it uses
(``BoardDiscussing``), so a unit test runs it with the real service on the typed fakes. Their
catalogue entries are built here too (``board_discussion_tools``) and placed by
``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Protocol

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..repositories.discussions import ThreadState
from ..schemas.discussions import DiscussionCreate, DiscussionScope
from .agent_tools_discussions import OTHERS_WORDS, flag, thread_state, thread_view, validated
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .discussions import DiscussionService

LIST_DEFAULT = 50
LIST_LIMIT = 100
# How many threads list_discussions reads before it keeps the unread or own ones; a guard.
FILTER_WINDOW = 500
SCOPES: Final[Mapping[str, DiscussionScope]] = {"board": "board", "ticket": "ticket"}
STATES: Final[Mapping[str, ThreadState]] = {"open": "open", "closed": "closed"}
OPEN_NEXT_STEP: Final = (
    "Others find the thread with list_discussions and answer with reply_discussion; read their "
    "answers with read_discussion."
)


class BoardDiscussing(Protocol):
    """What the tools for discussions on the board use of the composition root."""

    @property
    def discussion(self) -> DiscussionService: ...


def _choice[Value](args: ToolArguments, key: str, choices: Mapping[str, Value]) -> Value | None:
    value = _text(args.get(key))
    if value is None:
        return None
    chosen = choices.get(value)
    if chosen is None:
        raise ValidationFailure(
            f"{key} must be one of " + ", ".join(choices),
            details={"argument": key, "choices": list(choices)},
        )
    return chosen


def listed_row(entry: Mapping[str, object]) -> ToolResult:
    """One thread as list_discussions names it: where it lives and stands, never what was said."""
    return {
        "discussion_id": entry["id"],
        "title": entry["title"],
        "status": entry["status"],
        "state": thread_state(entry["status"]),
        "card_id": entry.get("card_id"),
        "ticket_key": entry.get("ticket_key"),
        "opened_by": entry.get("created_by_name"),
        "opened_by_me": bool(entry.get("opened_by_me")),
        "last_activity_at": entry.get("last_activity_at"),
        "message_count": entry.get("message_count"),
        "unread": bool(entry.get("unread")),
    }


def open_discussion(
    services: BoardDiscussing, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    title = _require(args, "title")
    question = _require(args, "question")
    payload = validated(
        DiscussionCreate,
        {"title": title, "goal": question, "mode": "manual", "participant_ids": []},
        {"goal": "question"},
    )
    created = services.discussion.create(
        actor, board_id, payload, ticket=_text(args.get("ticket"))
    )
    view = thread_view(created)
    view["next_step"] = OPEN_NEXT_STEP
    return view


def list_discussions(
    services: BoardDiscussing, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:read")
    board_id = _require(args, "board_id")
    scope = _choice(args, "scope", SCOPES)
    state = _choice(args, "state", STATES)
    unread = bool(flag(args, "unread"))
    mine = bool(flag(args, "mine"))
    limit = _whole_number(args, "limit", default=LIST_DEFAULT, maximum=LIST_LIMIT)
    narrowed = unread or mine
    entries = services.discussion.list(
        board_id,
        scope=scope,
        state=state,
        limit=FILTER_WINDOW if narrowed else limit + 1,
        reader=actor,
    )
    kept = [
        entry
        for entry in entries
        if (not unread or entry.get("unread")) and (not mine or entry.get("opened_by_me"))
    ]
    return {
        "board_id": board_id,
        "discussions": [listed_row(entry) for entry in kept[:limit]],
        "more": len(kept) > limit,
    }


def close_discussion(
    services: BoardDiscussing, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    return thread_view(services.discussion.close(actor, board_id, discussion_id))


def reopen_discussion(
    services: BoardDiscussing, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    return thread_view(services.discussion.reopen(actor, board_id, discussion_id))


def _flag_argument(description: str) -> ArgumentSchema:
    return {"type": "boolean", "description": description}


def board_discussion_tools(board_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of the tools for discussions on the board, in catalogue order."""
    discussion_id = string_argument("Discussion identifier from list_discussions or ask_agents")
    return [
        AgentTool(
            name="open_discussion",
            description=(
                "Open a discussion on the board itself, with a title and a question and no "
                "Ticket, addressed to nobody in particular: no local agent takes part and no "
                "round runs. People and other keys find it with list_discussions and answer with "
                "reply_discussion; you close it with close_discussion. " + OTHERS_WORDS
            ),
            scopes=("discussions:write",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "title": string_argument("What the thread is about, at most 200 characters"),
                    "question": string_argument("Your question or status, Markdown"),
                    "ticket": string_argument(
                        "Optional Ticket id or key on the board the question points at"
                    ),
                },
                required=["board_id", "title", "question"],
            ),
            handler=open_discussion,
        ),
        AgentTool(
            name="list_discussions",
            description=(
                "List a board's discussions, newest activity first: id, title, status, state "
                "(open or closed), the Ticket if any, who opened it and whether you did, the "
                "last activity, the message count and whether something is new for you (unread). "
                "Never a message's text; read one with read_discussion. " + OTHERS_WORDS
            ),
            scopes=("discussions:read",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "scope": string_argument(
                        "Optional: board (no Ticket) or ticket (on a Ticket); both unless given"
                    ),
                    "state": string_argument("Optional: open or closed; both unless given"),
                    "unread": _flag_argument("Only the threads with something new for you"),
                    "mine": _flag_argument("Only the threads you opened"),
                    "limit": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": LIST_LIMIT,
                        "description": f"At most this many threads; {LIST_DEFAULT} unless given",
                    },
                },
                required=["board_id"],
            ),
            handler=list_discussions,
        ),
        AgentTool(
            name="close_discussion",
            description=(
                "Close a discussion you opened: it starts no round from then on and still takes "
                "comments, each marked as written after the close. Nothing is deleted. Anyone "
                "else is refused with 403 not_opener."
            ),
            scopes=("discussions:write",),
            input_schema=object_schema(
                {"board_id": board_id, "discussion_id": discussion_id},
                required=["board_id", "discussion_id"],
            ),
            handler=close_discussion,
        ),
        AgentTool(
            name="reopen_discussion",
            description=(
                "Open a closed discussion again. The one who opened it or a signed-in person may; "
                "another key is refused with 403 not_opener."
            ),
            scopes=("discussions:write",),
            input_schema=object_schema(
                {"board_id": board_id, "discussion_id": discussion_id},
                required=["board_id", "discussion_id"],
            ),
            handler=reopen_discussion,
        ),
    ]


__all__ = [
    "BoardDiscussing",
    "board_discussion_tools",
    "close_discussion",
    "list_discussions",
    "listed_row",
    "open_discussion",
    "reopen_discussion",
]
