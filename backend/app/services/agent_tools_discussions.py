"""The worker tools for discussions: ask the board's agents, read a thread, reply in it.

A thread answers as data: the newest round's decision support (``synthesis``), each participant's
current position (``positions``) and the messages, where a participant's structured answer
(``answer``) stands in for its prose unless the worker asks for the prose (``include_prose``). A
person's message and an answer kept as prose always carry their ``content``.

Each handler is public and typed on the attributes of the composition root it uses
(``DiscussionReading``, ``DiscussionReplying``, ``DiscussionAsking``), so a unit test runs it with
the real services on the typed fakes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, TypeIs

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure
from ..schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number
from .agent_tools_write import DEDUPE_WINDOW_SECONDS, _seconds_since

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .agents import AgentService
    from .discussions import DiscussionEntry, DiscussionService
    from .runs import RunService

MAX_ROUNDS = 4


class DiscussionReading(Protocol):
    """What ``read_discussion`` uses of the composition root."""

    @property
    def discussion(self) -> DiscussionService: ...


class DiscussionReplying(Protocol):
    """What ``reply_discussion`` uses of the composition root."""

    @property
    def discussion(self) -> DiscussionService: ...

    @property
    def run(self) -> RunService: ...


class DiscussionAsking(Protocol):
    """What ``ask_agents`` uses of the composition root."""

    @property
    def agent(self) -> AgentService: ...

    @property
    def discussion(self) -> DiscussionService: ...

    @property
    def run(self) -> RunService: ...


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _rows(value: object) -> list[Mapping[str, object]]:
    """A thread's ``messages`` or ``positions``: the rows the discussion service lists."""
    if not _is_list(value):
        raise TypeError(f"a thread lists rows, not {type(value).__name__}")
    return [row for row in value if _is_mapping(row)]


def _message(message: Mapping[str, object], *, include_prose: bool) -> ToolResult:
    answer = message.get("answer")
    entry: ToolResult = {
        "id": message["id"],
        "author": message["author_name"],
        "author_type": message["author_type"],
        "round_number": message.get("round_number"),
        "created_at": message["created_at"],
        "answer": answer,
    }
    prose_only = not _is_mapping(answer) or answer.get("format") == "prose"
    if include_prose or prose_only:
        entry["content"] = message["content"]
    return entry


def thread_view(thread: DiscussionEntry, *, include_prose: bool = False) -> ToolResult:
    """A thread as a worker reads it: decision support and positions first, then the messages."""
    return {
        "discussion_id": thread["id"],
        "title": thread["title"],
        "status": thread["status"],
        "goal": thread["goal"],
        "card_id": thread.get("card_id"),
        "run_state": thread.get("run_state"),
        "synthesis": thread.get("synthesis"),
        "positions": [
            {
                "agent": stance["participant"],
                "participant_id": stance["participant_id"],
                "position": stance["position"],
                "recommendation": stance["recommendation"],
                "confidence": stance["confidence"],
                "round_number": stance["round_number"],
            }
            for stance in _rows(thread.get("positions", []))
        ],
        "messages": [
            _message(message, include_prose=include_prose)
            for message in _rows(thread.get("messages", []))
        ],
    }


def _include_prose(args: ToolArguments) -> bool:
    value = args.get("include_prose", False)
    if not isinstance(value, bool):
        raise ValidationFailure(
            "include_prose must be true or false", details={"argument": "include_prose"}
        )
    return value


def _run_view(run: Mapping[str, object] | None) -> ToolResult | None:
    if run is None:
        return None
    return {
        "id": run.get("run_id"),
        "status": run.get("run_status") or run.get("status"),
        "stop_reason": run.get("stop_reason"),
        "answers": run.get("answers"),
        "failures": run.get("failures") or [],
    }


def read_discussion(
    services: DiscussionReading, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:read")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    include_prose = _include_prose(args)
    thread = services.discussion.get(board_id, discussion_id)
    return thread_view(thread, include_prose=include_prose)


def reply_discussion(
    services: DiscussionReplying, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    discussion_id = _require(args, "discussion_id")
    content = _require(args, "content")
    include_prose = _include_prose(args)
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
            run = services.run.start(actor, board_id, discussion_id, rounds=1, autonomous=False)
        except Conflict as error:
            # A run already active is not a failure: the message is posted and the caller can poll.
            run = {"status": "running", "stop_reason": error.code}
    thread = services.discussion.get(board_id, discussion_id)
    view = thread_view(thread, include_prose=include_prose)
    view["run"] = _run_view(run)
    return view


def ask_agents(services: DiscussionAsking, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("discussions:write")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    question = _require(args, "question")
    include_prose = _include_prose(args)
    max_rounds = _whole_number(args, "rounds", default=1, maximum=MAX_ROUNDS)
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
            thread = services.discussion.get(board_id, str(existing["id"]))
            view = thread_view(thread, include_prose=include_prose)
            view["deduplicated"] = True
            return view
    created = services.discussion.create(
        actor,
        board_id,
        DiscussionCreate(
            card_id=card_id,
            goal=question,
            mode="roundtable",
            participant_ids=participants[:12],
            max_rounds=max_rounds,
        ),
    )
    run = services.run.start(actor, board_id, str(created["id"]), rounds=1, autonomous=False)
    thread = services.discussion.get(board_id, str(created["id"]))
    view = thread_view(thread, include_prose=include_prose)
    view["run"] = _run_view(run)
    return view


__all__ = [
    "DiscussionAsking",
    "DiscussionReading",
    "DiscussionReplying",
    "ask_agents",
    "read_discussion",
    "reply_discussion",
    "thread_view",
]
