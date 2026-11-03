"""``complete_ticket`` on the fakes: the real CardService, CommentService and LoopService on an
in-memory board, handed to the tool as the attributes ``TicketCompleting`` declares; then which
Tickets ``read_ticket`` offers it for, the longer comment it writes, and what ``tools/list`` and
``/llms.txt`` say about it.

The comments keep the service's own clock, so the dedupe window, which counts from the wall clock,
sees a comment written by this test as seconds old.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue, ValidationError

from app.api.mcp import INSTRUCTIONS, render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, ValidationFailure
from app.db.generated.board import CommentsRow
from app.schemas.subresources import CommentCreate
from app.services.agent_tools import allowed_actions, complete_ticket, tool_catalog
from app.services.agent_tools_tickets import completion_comment
from app.services.cards import CardService
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
    state: BoardState
    views: FakePlanViews


def ticket_world(settings: Settings) -> TicketWorld:
    """An executing Loop with a planned Ticket ``t`` (K-1), a human-only one ``h`` (K-2) that
    Grace confirms, and a manual one ``m``, all in Doing."""
    state = BoardState()
    loop = loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")
    state.loops = {LOOP: loop}
    state.lists = {"doing": list_row("doing", LOOP, 1024, name="Doing")}
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
    # Another summary on a completed Ticket only says so.
    other = complete_ticket(world, WORKER, done("m", "Shipped, really."))
    assert other["already_completed"] is True
    assert other["comment_id"] is None
    assert comments(world, "m") == ["Shipped."]


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


def test_complete_ticket_refuses_a_human_only_ticket_naming_who_confirms_it(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    with pytest.raises(Forbidden) as refused:
        complete_ticket(world, WORKER, done("h"))
    assert refused.value.code == "human_action_required"
    assert "Grace confirms it" in refused.value.message
    assert refused.value.details is not None
    assert {
        key: refused.value.details[key]
        for key in ("ticket_key", "confirmed_by", "human_instructions")
    } == {"ticket_key": "K-2", "confirmed_by": "Grace", "human_instructions": "Sign the contract"}
    assert world.state.cards["h"].completed_at is None
    assert comments(world, "h") == []


def test_complete_ticket_refuses_a_blocked_ticket_and_a_loop_that_is_not_executing(
    settings: Settings,
) -> None:
    world = ticket_world(settings)
    world.views.items = [readiness_item("t", ready=False, blockers=(BLOCKER,))]
    with pytest.raises(Conflict) as blocked:
        complete_ticket(world, WORKER, done("t"))
    assert (blocked.value.code, blocked.value.details) == (
        "ticket_blocked",
        {"blockers": [BLOCKER], "ticket_key": "K-1"},
    )
    world.views.items = [readiness_item("t")]
    world.state.loops[LOOP] = world.state.loops[LOOP].__replace__(stage="replanning")
    with pytest.raises(Conflict) as replanning:
        complete_ticket(world, WORKER, done("t"))
    assert replanning.value.code == "plan_change_required"
    assert world.state.cards["t"].completed_at is None
    assert comments(world, "t") == []


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
    world.state.cards["m"] = world.state.cards["m"].__replace__(
        completed_at=None, archived_at=CREATED
    )
    assert not offered("m")


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
