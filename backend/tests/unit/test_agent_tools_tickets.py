"""``complete_ticket`` on the fakes: the real CardService, CommentService and LoopService on an
in-memory board, handed to the tool as the attributes ``TicketCompleting`` declares; then which
Tickets ``read_ticket`` offers it for, the longer comment it writes, and what ``tools/list`` and
``/llms.txt`` say about it.

The comments keep the service's own clock, so the dedupe window, which counts from the wall clock,
sees a comment written by this test as seconds old.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue, ValidationError

from app.api.mcp import INSTRUCTIONS, render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import ApiError, Conflict, Forbidden, ValidationFailure
from app.db.generated.board import CommentsRow
from app.schemas.subresources import CommentCreate
from app.services.agent_tools import (
    ToolResult,
    allowed_actions,
    comment_ticket,
    complete_ticket,
    create_ticket,
    tool_catalog,
)
from app.services.agent_tools_tickets import completion_comment
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.subresources import CommentService
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import BLOCKER, FakePlanViews, plan_views, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
WORKER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"cards:read", "cards:write", "comments:write", "loops:read"}),
)
MOVER = ActorContext(
    actor_id="agent-2",
    actor_type="agent",
    actor_name="Mover",
    scopes=frozenset({"cards:write"}),
)


@dataclass(frozen=True, slots=True)
class TicketWorld:
    """What ``complete_ticket`` declares it uses of the composition root, and the board."""

    card: CardService
    comment: CommentService
    loop: LoopService
    list: ListService
    state: BoardState
    views: FakePlanViews


def ticket_world(settings: Settings) -> TicketWorld:
    """An executing Loop with a planned Ticket ``t`` (K-1), a human-only one ``h`` (K-2) that
    Grace confirms, and a manual one ``m``, all in Doing."""
    state = BoardState()
    loop = loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")
    state.loops = {LOOP: loop}
    state.lists = {
        "todo": list_row("todo", LOOP, 512, name="Todo"),
        "doing": list_row("doing", LOOP, 1024, name="Doing"),
    }
    state.cards = {
        "t": card_row("t", "doing", LOOP, plan_item_id="item-t").__replace__(
            ticket_key="K-1", kind="ticket"
        ),
        "h": card_row("h", "doing", LOOP).__replace__(
            ticket_key="K-2",
            required_actor="human",
            assignee_actor_id="person",
            assignee_type="user",
            assignee_name="Grace",
            human_instructions="Sign the contract",
        ),
        "m": card_row("m", "doing", LOOP),
    }
    views = FakePlanViews(items=[readiness_item("t")])
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    accounts = FakeRegistryUnitOfWork(RegistryState())
    cards = CardService(
        settings, checks, store, accounts, plans=plan_views(views), clock=lambda: NOW
    )
    return TicketWorld(
        card=cards,
        comment=CommentService(checks, store, accounts),
        loop=LoopService(
            settings, checks, store, plans=plan_views(views), tickets=cards, clock=lambda: NOW
        ),
        list=ListService(checks, store),
        state=state,
        views=views,
    )


def done(card_id: str, summary: str = "Shipped.", **more: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "card_id": card_id, "summary": summary, **more}


def comments(world: TicketWorld, card_id: str) -> list[str]:
    return [row.content for row in world.state.comments.values() if row.card_id == card_id]


def test_complete_ticket_completes_a_ready_ticket_and_comments_the_summary_and_evidence(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    answer = complete_ticket(
        world, WORKER, done("t", evidence=["commit 1a2b3c", " ", "pytest: 12 passed"])
    )
    card = world.state.cards["t"]
    assert (card.completed_at, card.version) == (STAMP, 2)
    assert comments(world, "t") == [
        "Shipped.\n\n**Evidence**\n\n- commit 1a2b3c\n- pytest: 12 passed"
    ]
    (comment_id,) = world.state.comments
    loop = world.loop.get(BOARD_ID, LOOP)
    assert answer == {
        "ticket": {"id": "t", "key": "K-1", "completed_at": STAMP, "version": 2},
        "comment_id": comment_id,
        "loop": {"stage": loop["stage"], "progress": loop["progress"]},
    }
    assert (loop["progress"]["ticket_total"], loop["progress"]["ticket_completed"]) == (1, 1)


def test_complete_ticket_answers_the_first_result_for_the_same_summary_and_writes_nothing_else(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    first = complete_ticket(world, WORKER, done("m"))
    again = complete_ticket(world, WORKER, done("m"))
    assert again == first | {"deduplicated": True}
    assert comments(world, "m") == ["Shipped."]
    assert world.state.cards["m"].version == 2


def test_complete_ticket_keeps_another_summary_on_a_completed_ticket_once(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    complete_ticket(world, WORKER, done("m"))
    other = complete_ticket(world, WORKER, done("m", "Shipped, really."))
    assert other["already_completed"] is True
    assert other["comment_id"] is not None
    retried = complete_ticket(world, WORKER, done("m", "Shipped, really."))
    assert (retried["comment_id"], retried["deduplicated"]) == (other["comment_id"], True)
    assert comments(world, "m") == ["Shipped.", "Shipped, really."]
    assert world.state.cards["m"].version == 2


def test_complete_ticket_counts_the_dedupe_window_from_the_first_comment(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    world.state.cards["m"] = world.state.cards["m"].__replace__(completed_at=CREATED)
    world.state.comments["old"] = CommentsRow(
        id="old",
        card_id="m",
        actor_id=WORKER.actor_id,
        content="Shipped.",
        created_at=CREATED,
        updated_at=CREATED,
    )
    answer = complete_ticket(world, WORKER, done("m"))
    assert answer["already_completed"] is True
    assert "deduplicated" not in answer
    assert comments(world, "m") == ["Shipped.", "Shipped."]


def comment_of(refusal: ApiError) -> object:
    assert refusal.details is not None
    return refusal.details["comment_id"]


def test_complete_ticket_refuses_a_human_only_ticket_naming_who_confirms_it_and_keeps_the_summary(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    with pytest.raises(Forbidden) as refused:
        complete_ticket(world, WORKER, done("h"))
    assert refused.value.code == "human_action_required"
    assert "Grace confirms it" in refused.value.message
    assert "summary is saved as a comment" in refused.value.message
    assert refused.value.details is not None
    assert {
        key: refused.value.details[key]
        for key in ("ticket_key", "confirmed_by", "human_instructions")
    } == {"ticket_key": "K-2", "confirmed_by": "Grace", "human_instructions": "Sign the contract"}
    assert world.state.cards["h"].completed_at is None
    assert comments(world, "h") == ["Shipped."]
    # A retry meets the same refusal and finds the comment it already wrote.
    with pytest.raises(Forbidden) as again:
        complete_ticket(world, WORKER, done("h"))
    assert comment_of(again.value) == comment_of(refused.value)
    assert comments(world, "h") == ["Shipped."]


def test_complete_ticket_refuses_a_blocked_ticket_and_a_loop_that_is_not_executing(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    world.views.items = [readiness_item("t", ready=False, blockers=(BLOCKER,))]
    with pytest.raises(Conflict) as blocked:
        complete_ticket(world, WORKER, done("t"))
    assert blocked.value.code == "ticket_blocked"
    assert blocked.value.details == {
        "blockers": [BLOCKER],
        "ticket_key": "K-1",
        "comment_id": comment_of(blocked.value),
    }
    world.views.items = [readiness_item("t")]
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(stage="replanning")
    with pytest.raises(Conflict) as replanning:
        complete_ticket(world, WORKER, done("t", "Waiting for the new plan."))
    assert replanning.value.code == "plan_change_required"
    assert world.state.cards["t"].completed_at is None
    assert comments(world, "t") == ["Shipped.", "Waiting for the new plan."]


def test_complete_ticket_writes_nothing_in_a_loop_that_is_read_only(settings: Settings) -> None:
    world = ticket_world(settings)
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(
        stage="completed", completed_at=CREATED
    )
    with pytest.raises(Conflict) as closed:
        complete_ticket(world, WORKER, done("m"))
    assert closed.value.code == "loop_read_only"
    assert comments(world, "m") == []


def note(card_id: str, content: str) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "card_id": card_id, "content": content}


def test_comment_ticket_comments_a_ticket_done_or_not_and_answers_a_retry_with_the_first(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    complete_ticket(world, WORKER, done("m"))
    later = "Superseded by L-2: the export moved there."
    first = comment_ticket(world, WORKER, note("m", later))
    assert (first["actor"], first["content"]) == (None, later)
    assert comment_ticket(world, WORKER, note("m", later)) == first | {"deduplicated": True}
    comment_ticket(world, WORKER, note("t", "Started."))
    assert comments(world, "m") == ["Shipped.", later]
    assert comments(world, "t") == ["Started."]


def test_comment_ticket_is_refused_only_where_nothing_may_be_written(settings: Settings) -> None:
    world = ticket_world(settings)
    with pytest.raises(Forbidden):
        comment_ticket(world, MOVER, note("m", "Hello"))
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(
        stage="completed", completed_at=CREATED
    )
    with pytest.raises(Conflict) as closed:
        comment_ticket(world, WORKER, note("m", "Hello"))
    assert closed.value.code == "loop_read_only"
    assert comments(world, "m") == []


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def part(answer: ToolResult, key: str) -> Mapping[str, object]:
    value = answer[key]
    assert _is_mapping(value)
    return value


def ask(title: str, **more: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "loop_id": LOOP, "title": title, **more}


def test_create_ticket_adds_work_outside_the_plan_in_the_first_column(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    answer = create_ticket(
        world, WORKER, ask("Rename the export", description="It still says CSV.", priority="low")
    )
    card = world.state.cards[str(part(answer, "ticket")["id"])]
    assert (card.kind, card.ticket_key, card.list_id, card.priority) == (
        "manual",
        "L-1-UNP-001",
        "todo",
        "low",
    )
    assert card.description == "It still says CSV."
    assert answer == {
        "ticket": {
            "id": card.id,
            "key": "L-1-UNP-001",
            "title": "Rename the export",
            "column": "Todo",
            "version": 1,
            "state": "ready",
            "workplace": "unknown",
            "labels": [],
        },
        "unplanned": True,
    }
    readiness = world.loop.readiness(BOARD_ID, LOOP)
    assert [entry["key"] for entry in readiness["unplanned"]] == ["L-1-UNP-001"]
    # It is not a planned Ticket, so it never blocks: no readiness item, no blocker.
    assert all(item["card_id"] != card.id for item in readiness["items"])


def test_create_ticket_as_a_follow_up_points_both_ways_and_a_retry_answers_the_first(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    first = create_ticket(world, WORKER, ask("Fix the date", follow_up_of="t"))
    again = create_ticket(world, WORKER, ask("Fix the date", follow_up_of="t"))
    card = world.state.cards[str(part(first, "ticket")["id"])]
    assert card.description == "Follow-up of K-1: "
    assert comments(world, "t") == ["Follow-up: L-1-UNP-001 - Fix the date"]
    follow_up = part(first, "follow_up_of")
    assert (follow_up["id"], follow_up["key"]) == ("t", "K-1")
    assert again == first | {"deduplicated": True}
    assert [row.ticket_key for row in world.state.cards.values() if row.kind == "manual"] == [
        "L-1-UNP-001"
    ]


def test_create_ticket_is_refused_where_the_plan_is_not_executing(settings: Settings) -> None:
    world = ticket_world(settings)
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(stage="replanning")
    with pytest.raises(Conflict) as refused:
        create_ticket(world, WORKER, ask("Too late"))
    assert refused.value.code == "plan_change_required"
    with pytest.raises(ValidationFailure, match="priority"):
        create_ticket(world, WORKER, ask("Odd", priority="whenever"))
    with pytest.raises(ValidationFailure, match="title"):
        create_ticket(world, WORKER, ask("x" * 201))
    with pytest.raises(Forbidden):
        create_ticket(world, MOVER, ask("No comments scope"))
    assert all(card.kind != "manual" for card in world.state.cards.values() if card.id != "m")


def test_complete_ticket_needs_both_scopes_and_list_evidence(settings: Settings) -> None:
    world = ticket_world(settings)
    with pytest.raises(Forbidden):
        complete_ticket(world, MOVER, done("m"))
    with pytest.raises(ValidationFailure, match="evidence"):
        complete_ticket(world, WORKER, done("m", evidence="a commit"))
    assert world.state.cards["m"].completed_at is None


def test_allowed_actions_offer_complete_ticket_only_for_a_ready_open_ticket_of_a_worker(
    settings: Settings,
) -> None:
    world = ticket_world(settings)

    def offered(card_id: str, *, execution_allowed: bool = True) -> bool:
        card = world.card.get(BOARD_ID, LOOP, card_id)
        return "complete_ticket" in allowed_actions(card, execution_allowed=execution_allowed)

    assert offered("t") and offered("m")
    assert offered("m", execution_allowed=False)
    assert not offered("t", execution_allowed=False)
    assert not offered("h")
    world.views.items = [readiness_item("t", ready=False, blockers=(BLOCKER,))]
    assert not offered("t")
    world.state.cards["m"] = world.state.cards["m"].__replace__(completed_at=CREATED)
    assert not offered("m")
    card = world.card.get(BOARD_ID, LOOP, "m")
    assert "comment_ticket" in allowed_actions(card, execution_allowed=True)
    world.state.cards["m"] = world.state.cards["m"].__replace__(
        completed_at=None, archived_at=CREATED
    )
    assert not offered("m")
    archived = world.card.get(BOARD_ID, LOOP, "m")
    assert allowed_actions(archived, execution_allowed=True) == ["comment_ticket"]


def test_a_comment_holds_a_completion_summary_not_only_a_title() -> None:
    long = "x" * 5000
    assert CommentCreate(content=long).content == long
    with pytest.raises(ValidationError):
        CommentCreate(content="x" * 20_001)
    with pytest.raises(ValidationError):
        CommentCreate(content="   ")
    assert completion_comment("Done.", []) == "Done."


def test_complete_ticket_is_described_in_tools_list_and_llms_txt(settings: Settings) -> None:
    tool = tool_catalog()["complete_ticket"]
    assert tool.scopes == ("cards:write", "comments:write")
    assert tool.input_schema["required"] == ["board_id", "card_id", "summary"]
    assert "complete_ticket" in [entry["name"] for entry in tool_list(WORKER)]
    assert "complete_ticket" not in [entry["name"] for entry in tool_list(MOVER)]
    text = render_bootstrap(settings)
    assert "A Ticket is done through `complete_ticket`" in text
    assert "a column named Done completes nothing" in text
    assert "complete_ticket" in INSTRUCTIONS
