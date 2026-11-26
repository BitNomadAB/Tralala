"""The discussion tools on the fakes: ``ask_agents``, ``read_discussion`` and ``reply_discussion``
run DiscussionService, RunService and the round engine with a scripted provider, handed only the
attributes of the composition root their Protocols declare; then what ``tools/list`` says."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.dates import utcnow
from app.core.errors import Forbidden, ValidationFailure
from app.schemas.discussions import DiscussionMessageCreate
from app.services.agent_tools import ToolResult, ask_agents, read_discussion, reply_discussion
from app.services.agent_tools_discussions import OTHERS_WORDS
from app.services.agents import AgentService
from app.services.discussions import DiscussionService
from app.services.runs import RunService
from tests.unit.fakes.board import BOARD_ID
from tests.unit.fakes.registry import registry_unit_of_work
from tests.unit.test_discussion_services import CARD, THREAD, World, answer, said, world

WORKER = ActorContext(
    actor_id="worker-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"discussions:read", "discussions:write"}),
)


@dataclass(frozen=True)
class Tools:
    """The attributes of the composition root the discussion tools use."""

    agent: AgentService
    discussion: DiscussionService
    run: RunService


def tools(w: World, settings: Settings) -> Tools:
    return Tools(AgentService(settings, registry_unit_of_work(w.registry)), w.discussions, w.runs)


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def rows(result: ToolResult, key: str) -> list[Mapping[str, object]]:
    value = result[key]
    assert _is_list(value)
    found = [row for row in value if _is_mapping(row)]
    assert len(found) == len(value)
    return found


def field(row: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = row[key]
    assert _is_mapping(value)
    return value


def answered(w: World) -> None:
    w.agents.scripts = {
        "alpha": [answer("Small change.", tokens=4)],
        "beta": [said("I would rather wait.", tokens=5), said("Still prose.", tokens=6)],
    }
    w.runs.start(
        ActorContext(actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=WORKER.scopes),
        BOARD_ID,
        THREAD,
        rounds=1,
        background=False,
    )


def test_read_discussion_answers_the_synthesis_positions_and_the_structure(
    settings: Settings,
) -> None:
    w = world("alpha", "beta")
    answered(w)
    result = read_discussion(
        tools(w, settings), WORKER, {"board_id": BOARD_ID, "discussion_id": THREAD}
    )
    synthesis = field(result, "synthesis")
    assert field(synthesis, "suggestion") == {
        "verdict": "unclear",
        "reason": "Not settled yet: 1 for going ahead and 1 cannot tell; read the open questions.",
    }
    assert [(p["agent"], p["position"]) for p in rows(result, "positions")] == [
        ("Alpha", "yes"),
        ("Beta", "unclear"),
    ]
    alpha, beta = rows(result, "messages")
    assert field(alpha, "answer")["recommendation"] == "Recommend: Small change."
    # A structured answer leaves its prose out unless asked; a prose-only answer keeps it.
    assert "content" not in alpha
    assert beta["content"] == "I would rather wait."
    full = read_discussion(
        tools(w, settings),
        WORKER,
        {"board_id": BOARD_ID, "discussion_id": THREAD, "include_prose": True},
    )
    assert rows(full, "messages")[0]["content"] == "Small change."


def test_read_discussion_needs_its_scope_and_a_boolean_for_the_prose(settings: Settings) -> None:
    w = world("alpha")
    reader = ActorContext(actor_id="x", actor_type="agent", actor_name="X", scopes=frozenset())
    with pytest.raises(Forbidden):
        read_discussion(tools(w, settings), reader, {"board_id": BOARD_ID, "discussion_id": THREAD})
    with pytest.raises(ValidationFailure, match="include_prose"):
        read_discussion(
            tools(w, settings),
            WORKER,
            {"board_id": BOARD_ID, "discussion_id": THREAD, "include_prose": "yes"},
        )


def test_reply_discussion_posts_and_runs_one_round(settings: Settings) -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Answered.", "no")]}
    result = reply_discussion(
        tools(w, settings),
        WORKER,
        {"board_id": BOARD_ID, "discussion_id": THREAD, "content": "What about the rollback?"},
    )
    run = field(result, "run")
    assert run["status"] == "completed"
    messages = rows(result, "messages")
    assert [m["author"] for m in messages] == ["Worker", "Alpha"]
    assert messages[0]["content"] == "What about the rollback?"
    assert messages[0]["answer"] is None
    assert field(field(result, "synthesis"), "suggestion")["verdict"] == "no"


def test_ask_agents_opens_a_thread_and_answers_with_the_round(settings: Settings) -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Ship it.", "yes")]}
    result = ask_agents(
        tools(w, settings),
        WORKER,
        {"board_id": BOARD_ID, "card_id": CARD, "question": "Ship it?", "agent_ids": ["alpha"]},
    )
    assert field(result, "run")["answers"] == 1
    assert field(field(result, "synthesis"), "suggestion") == {
        "verdict": "yes",
        "reason": "Every participant supports going ahead.",
    }
    assert [p["position"] for p in rows(result, "positions")] == ["yes"]
    with pytest.raises(ValidationFailure, match="rounds must be between 1 and 4"):
        ask_agents(
            tools(w, settings),
            WORKER,
            {"board_id": BOARD_ID, "card_id": CARD, "question": "Again?", "rounds": 9},
        )


def test_ask_agents_without_an_agent_on_the_board_says_so(settings: Settings) -> None:
    w = world()
    with pytest.raises(ValidationFailure) as refused:
        ask_agents(
            tools(w, settings), WORKER, {"board_id": BOARD_ID, "card_id": CARD, "question": "Q?"}
        )
    assert refused.value.code == "no_agents_available"


def test_the_tool_list_offers_the_prose_switch_on_all_three() -> None:
    listed = {entry["name"]: entry for entry in tool_list(WORKER)}
    for name in ("ask_agents", "read_discussion", "reply_discussion"):
        assert "include_prose" in field(field(listed[name], "inputSchema"), "properties")


def test_the_discussion_tools_say_that_titles_and_messages_are_data() -> None:
    listed = {entry["name"]: entry for entry in tool_list(WORKER)}
    for name in ("ask_agents", "read_discussion", "reply_discussion"):
        assert str(listed[name]["description"]).endswith(" " + OTHERS_WORDS)
    assert field(listed["ask_agents"], "inputSchema")["required"] == ["board_id", "question"]


# --- ask_agents on the board, in the background and twice -----------------------------------------


def on_the_board(w: World) -> None:
    """THREAD is a discussion on the board with the given title, no Ticket."""
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        card_id=None, title="Who touches the API?"
    )


def test_ask_agents_without_a_ticket_opens_a_discussion_on_the_board_under_its_title(
    settings: Settings,
) -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("Nobody yet.", "yes")]}
    result = ask_agents(
        tools(w, settings),
        WORKER,
        {
            "board_id": BOARD_ID,
            "title": "Who touches the API?",
            "question": "Is anyone changing the API?",
            "agent_ids": ["alpha"],
        },
    )
    assert (result["card_id"], result["title"], result["state"]) == (
        None,
        "Who touches the API?",
        "open",
    )
    assert result["opened_by_me"] is True
    assert field(result, "run")["answers"] == 1
    assert "next_step" not in result
    stored = w.state.discussions[str(result["discussion_id"])]
    assert (stored.card_id, stored.created_by_actor_id) == (None, WORKER.actor_id)


def test_ask_agents_without_a_ticket_or_a_title_names_the_missing_argument(
    settings: Settings,
) -> None:
    w = world("alpha")
    with pytest.raises(ValidationFailure) as refused:
        ask_agents(tools(w, settings), WORKER, {"board_id": BOARD_ID, "question": "Q?"})
    assert refused.value.details == {"argument": "title"}
    with pytest.raises(ValidationFailure) as too_long:
        ask_agents(
            tools(w, settings),
            WORKER,
            {"board_id": BOARD_ID, "title": "t" * 201, "question": "Q?", "agent_ids": ["alpha"]},
        )
    assert too_long.value.details == {"argument": "title"}


def test_ask_agents_in_the_background_answers_at_once_with_the_thread_and_the_next_step(
    settings: Settings,
) -> None:
    w = world("alpha")
    w.runs.shutdown()  # nothing executes the round: the answer is the one before it runs
    result = ask_agents(
        tools(w, settings),
        WORKER,
        {
            "board_id": BOARD_ID,
            "card_id": CARD,
            "question": "Ship it?",
            "agent_ids": ["alpha"],
            "background": True,
        },
    )
    assert field(result, "run")["status"] == "running"
    assert result["discussion_id"] in w.state.discussions
    assert "read_discussion" in str(result["next_step"])
    assert w.agents.calls == []
    with pytest.raises(ValidationFailure, match="background must be true or false"):
        ask_agents(
            tools(w, settings),
            WORKER,
            {"board_id": BOARD_ID, "card_id": CARD, "question": "Q?", "background": "yes"},
        )


def test_ask_agents_answers_the_same_question_again_with_the_first_thread(
    settings: Settings,
) -> None:
    w = world("alpha")
    w.agents.scripts = {"alpha": [answer("One.", "yes"), answer("Two.", "yes")]}
    asked: dict[str, JsonValue] = {
        "board_id": BOARD_ID,
        "title": "Who touches the API?",
        "question": "Anyone?",
        "agent_ids": ["alpha"],
    }
    first = ask_agents(tools(w, settings), WORKER, asked)
    first_id = str(first["discussion_id"])
    # The fixed clock lies in the past; the guard compares with the real time.
    w.state.discussions[first_id] = w.state.discussions[first_id].__replace__(
        created_at=utcnow(), status="discussing"
    )
    again = ask_agents(tools(w, settings), WORKER, asked)
    assert (again["discussion_id"], again["deduplicated"]) == (first_id, True)
    other = ask_agents(tools(w, settings), WORKER, {**asked, "title": "Another title"})
    assert other["discussion_id"] != first_id
    assert "deduplicated" not in other


# --- reply_discussion: when a round runs --------------------------------------------------------


def reply(w: World, settings: Settings, **extra: JsonValue) -> ToolResult:
    arguments: dict[str, JsonValue] = {
        "board_id": BOARD_ID,
        "discussion_id": THREAD,
        "content": "Status: done with the API.",
        **extra,
    }
    return reply_discussion(tools(w, settings), WORKER, arguments)


def test_reply_discussion_in_a_thread_without_local_agents_keeps_the_message_and_runs_nothing(
    settings: Settings,
) -> None:
    w = world()
    result = reply(w, settings, run=True)
    assert (result["run"], result["run_skipped"]) == (None, "no_participants")
    assert [m.content for m in w.state.discussion_messages] == ["Status: done with the API."]
    assert w.state.runs == {}


def test_reply_discussion_in_a_closed_thread_keeps_a_comment_after_the_close(
    settings: Settings,
) -> None:
    w = world("alpha")
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status="closed")
    result = reply(w, settings)
    assert (result["run"], result["run_skipped"], result["state"]) == (
        None,
        "thread_closed",
        "closed",
    )
    (message,) = rows(result, "messages")
    assert message["after_closed"] is True
    assert (w.state.runs, w.agents.calls) == ({}, [])


def test_reply_discussion_runs_by_default_only_on_a_ticket_that_can_take_a_round(
    settings: Settings,
) -> None:
    w = world("alpha")
    on_the_board(w)
    # On the board a status answer costs no round unless run is true.
    quiet = reply(w, settings)
    assert (quiet["run"], "run_skipped" in quiet, w.agents.calls) == (None, False, [])
    w.agents.scripts = {"alpha": [answer("Noted.", "yes")]}
    asked = reply(w, settings, run=True)
    assert field(asked, "run")["status"] == "completed"
    # On a Ticket a decided thread keeps the message and says why no round ran.
    decided = world("alpha")
    decided.state.discussions[THREAD] = decided.state.discussions[THREAD].__replace__(
        status="approved"
    )
    result = reply(decided, settings)
    assert (result["run"], result["run_skipped"]) == (None, "thread_decided")
    assert reply(decided, settings, run=False).get("run_skipped") is None


def test_reply_discussion_points_at_a_ticket_and_runs_in_the_background(
    settings: Settings,
) -> None:
    w = world("alpha")
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(ticket_key="L-1-001", title="API")
    w.runs.shutdown()
    result = reply(w, settings, ticket="L-1-001", background=True)
    assert field(result, "run")["status"] == "running"
    assert "read_discussion" in str(result["next_step"])
    (message,) = rows(result, "messages")
    assert field(message, "ref_ticket")["ticket_key"] == "L-1-001"
    assert w.agents.calls == []


# --- read_discussion marks the thread read -------------------------------------------------------


def test_read_discussion_marks_the_thread_read_and_answers_its_state_and_messages(
    settings: Settings,
) -> None:
    w = world()
    on_the_board(w)
    ada = ActorContext(
        actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=WORKER.scopes
    )
    w.discussions.close(ada, BOARD_ID, THREAD)
    w.discussions.add_message(
        ada, BOARD_ID, THREAD, DiscussionMessageCreate(content="Late word.", ticket=CARD)
    )
    assert w.discussions.list(BOARD_ID, reader=WORKER)[0]["unread"] is True
    result = read_discussion(
        tools(w, settings), WORKER, {"board_id": BOARD_ID, "discussion_id": THREAD}
    )
    assert (result["title"], result["state"], result["card_id"]) == (
        "Who touches the API?",
        "closed",
        None,
    )
    assert result["closed_at"] is not None
    assert result["opened_by_me"] is False
    (message,) = rows(result, "messages")
    assert message["after_closed"] is True
    assert field(message, "ref_ticket")["card_id"] == CARD
    assert (THREAD, WORKER.actor_id) in w.state.discussion_reads
    assert w.discussions.list(BOARD_ID, reader=WORKER)[0]["unread"] is False
