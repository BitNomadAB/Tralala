"""The discussion tools on the fakes: ``ask_agents``, ``read_discussion`` and ``reply_discussion``
run DiscussionService, RunService and the round engine with a scripted provider, handed only the
attributes of the composition root their Protocols declare; then what ``tools/list`` says."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeIs

import pytest

from app.api.mcp import tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.services.agent_tools import ToolResult, ask_agents, read_discussion, reply_discussion
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
        "reason": "Beta cannot tell yet; read the open questions.",
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
