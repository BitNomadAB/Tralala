"""``loop_summaries`` on the fakes: the real LoopService and ListService on an in-memory board,
handed to the tool as the attributes ``LoopSummarising`` declares; what each Loop's row says comes
next and who does it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.db.generated.board import LoopsRow
from app.services.agent_tools import ToolResult, loop_summaries, tool_catalog
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.plan_views import ReadinessItem
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    document_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
READER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)


@dataclass(frozen=True, slots=True)
class LoopWorld:
    """What ``loop_summaries`` declares it uses of the composition root."""

    loop: LoopService
    list: ListService


def loop_world(
    settings: Settings,
    loops: list[LoopsRow],
    *,
    items: list[ReadinessItem] | None = None,
    state: BoardState | None = None,
) -> LoopWorld:
    """The Loops given, each with a Todo and a Doing column; every Loop answers ``items`` as its
    planned Tickets' readiness."""
    board = state or BoardState()
    board.loops = {loop.id: loop for loop in loops}
    for loop in loops:
        board.lists[f"todo-{loop.id}"] = list_row(f"todo-{loop.id}", loop.id, 512, name="Todo")
        board.lists[f"doing-{loop.id}"] = list_row(f"doing-{loop.id}", loop.id, 1024, name="Doing")
    views = plan_views(FakePlanViews(items=items or []))
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(board)
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
    )
    return LoopWorld(
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        list=ListService(checks, store),
    )


def loop(loop_id: str, stage: str, sequence: int, *, goal: str = "") -> LoopsRow:
    completed = CREATED if stage == "completed" else None
    return loop_row(loop_id, stage=stage, completed_at=completed).__replace__(
        sequence=sequence, key=f"L-{sequence}", goal=goal
    )


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(isinstance(row, Mapping) for row in value)


def rows(answer: ToolResult) -> list[Mapping[str, object]]:
    value = answer["loops"]
    assert _is_rows(value)
    return value


def ask(**arguments: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, **arguments}


def done(item: ReadinessItem) -> ReadinessItem:
    item["completed_at"] = CREATED
    item["state"] = None
    return item


# --- the rows ------------------------------------------------------------------------------------


def test_each_open_loop_says_what_comes_next_and_who_does_it(settings: Settings) -> None:
    state = BoardState()
    state.documents = [
        document_row("i2", "review", "info", content="Why"),
        document_row(
            "a2", "review", "analysis_ai", status="ready_for_review", revision=3, info="i2"
        ),
    ]
    world = loop_world(
        settings,
        [
            loop("draft", "draft", 1, goal="Know  what\nto fix " + "x" * 300),
            loop("review", "analysis_review", 2),
            loop("plan", "planning", 3),
            loop("old", "completed", 4),
        ],
        state=state,
    )
    answer = loop_summaries(world, READER, ask())
    draft, review, plan = rows(answer)
    assert answer["count"] == 3
    assert (draft["key"], draft["stage"], draft["waiting_on"]) == ("L-1", "draft", "person")
    assert draft["next"] == "Write the Loop's Info: what should change and why."
    assert str(draft["goal"]).startswith("Know what to fix x")
    assert len(str(draft["goal"])) == 280
    assert (review["waiting_on"], review["next"]) == (
        "person",
        "A person reviews the analysis and approves it or asks for changes.",
    )
    documents = review["documents"]
    assert isinstance(documents, Mapping)
    assert (documents["analysis_ai"], documents["info"], documents["roadmap"]) == (
        "ready_for_review r3",
        "draft r1",
        "empty",
    )
    assert (plan["waiting_on"], "hand one in" in str(plan["next"])) == ("agent", True)
    assert "list_tickets" in str(answer["next_step"])
    finished = rows(loop_summaries(world, READER, ask(include_completed=True)))[-1]
    assert (finished["key"], finished["waiting_on"]) == ("L-4", "nobody")
    assert "read-only" in str(finished["next"])


def test_a_loop_in_delivery_counts_its_tickets_by_state(settings: Settings) -> None:
    state = BoardState()
    state.cards = {
        "a": card_row("a", "todo-run", "run"),
        "b": card_row("b", "todo-run", "run"),
        "c": card_row("c", "doing-run", "run"),
        # Outside the plan: only its own wait holds it up (a third party: blocked).
        "u": card_row("u", "doing-run", "run").__replace__(
            kind="manual", ticket_key="L-1-UNP-001", waiting_for="third_party"
        ),
    }
    items = [
        readiness_item("x", ready=False, waiting_for="decision"),
        readiness_item("a"),
        readiness_item("b", human=True),
        readiness_item("c", ready=False),
        done(readiness_item("d")),
    ]
    world = loop_world(
        settings,
        [loop("run", "ready", 1).__replace__(current_plan_id="plan-1")],
        items=items,
        state=state,
    )
    (row,) = rows(loop_summaries(world, READER, ask()))
    # needs_input beats blocked, and a person answers it first.
    assert (row["next"], row["waiting_on"], row["execution_allowed"]) == (
        "1 Ticket waits for a person's decision, information or access.",
        "person",
        True,
    )
    assert row["tickets"] == {
        "ready": 2,
        "needs_input": 1,
        "blocked": 2,
        "completed": 1,
        "total": 6,
        "needs_person": 2,
        "by_column": {"Todo": 2, "Doing": 2},
    }
    ready = loop_world(settings, [loop("run", "ready", 1)], items=items[1:])
    (row,) = rows(loop_summaries(ready, READER, ask()))
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready to start.", "anyone")
    person_only = loop_world(settings, [loop("run", "in_progress", 1)], items=items[2:])
    (row,) = rows(loop_summaries(person_only, READER, ask()))
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready and needs a person.", "person")
    waiting = loop_world(settings, [loop("run", "ready", 1)], items=items[3:])
    (row,) = rows(loop_summaries(waiting, READER, ask()))
    assert (row["next"], row["waiting_on"]) == (
        "1 Ticket waits for earlier work or a third party.",
        "anyone",
    )
    finished = loop_world(settings, [loop("run", "ready", 1)], items=items[4:])
    (row,) = rows(loop_summaries(finished, READER, ask()))
    assert (row["waiting_on"], "accepts the implementation" in str(row["next"])) == ("person", True)


def test_no_ticket_count_or_ticket_sentence_names_an_agent(settings: Settings) -> None:
    """A person owns every Ticket: delivery never waits on an agent, and no count says one does
    the work; only a document may wait on an agent (decision support)."""
    for items in (
        [readiness_item("a")],
        [readiness_item("b", human=True)],
        [readiness_item("c", ready=False)],
        [readiness_item("x", waiting_for="access")],
    ):
        world = loop_world(settings, [loop("run", "in_progress", 1)], items=items)
        (row,) = rows(loop_summaries(world, READER, ask()))
        assert row["waiting_on"] in {"person", "anyone"}
        assert "agent" not in str(row["next"]).casefold()
        tickets = row["tickets"]
        assert isinstance(tickets, Mapping)
        assert "ready_for_agent" not in tickets
        assert "ready_for_person" not in tickets


def test_loop_summaries_narrows_to_a_stage_and_refuses_an_unknown_one(settings: Settings) -> None:
    world = loop_world(
        settings,
        [loop("draft", "draft", 1), loop("plan", "planning", 2), loop("old", "completed", 3)],
    )
    assert [row["key"] for row in rows(loop_summaries(world, READER, ask(stage="planning")))] == [
        "L-2"
    ]
    # Naming a finished stage lists finished Loops without include_completed.
    assert [row["key"] for row in rows(loop_summaries(world, READER, ask(stage="completed")))] == [
        "L-3"
    ]
    with pytest.raises(ValidationFailure, match="stage must be one of"):
        loop_summaries(world, READER, ask(stage="shipping"))
    with pytest.raises(Forbidden):
        loop_summaries(world, READER.__replace__(scopes=frozenset({"cards:read"})), ask())


def test_loop_summaries_is_offered_to_loops_read_and_documented(settings: Settings) -> None:
    assert tool_catalog()["loop_summaries"].scopes == ("loops:read",)
    assert "loop_summaries" in {tool["name"] for tool in tool_list(READER)}
    assert "### loop_summaries (requires `loops:read`)" in render_bootstrap(settings)
