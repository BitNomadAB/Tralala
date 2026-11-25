"""``move_ticket`` on the fakes: the real CardService and ListService on an in-memory board, handed
to the tool as the attributes ``TicketMoving`` declares.

A column is found by its id or by its name in any case. The tool tries a move again only after a
version conflict; any other refusal of ``CardService.move``, ``409 report_required`` above all, is
its answer as the service gave it. ``CountingCards`` is the real service, counting the moves it is
asked for, so a test sees whether a second attempt was made.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import override

import pytest
from pydantic import JsonValue

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, ValidationFailure, VersionConflict
from app.schemas.cards import CardMove
from app.services.agent_tools import _move_ticket
from app.services.cards import CardEntry, CardService
from app.services.lists import ListService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
KEY = ActorContext(
    actor_id="key-1",
    actor_type="agent",
    actor_name="Key",
    scopes=frozenset({"cards:read", "cards:write"}),
    credential_id="cred-1",
)


class CountingCards(CardService):
    """The real service; ``race`` runs once before the first move, as another writer would."""

    moves: int = 0
    race: Callable[[], None] | None = None

    @override
    def move(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardMove,
    ) -> CardEntry:
        self.moves += 1
        race, self.race = self.race, None
        if race is not None:
            race()
        return super().move(actor, board_id, loop_id, card_id, payload)


@dataclass(frozen=True, slots=True)
class MoveWorld:
    """What ``move_ticket`` declares it uses of the composition root, and the board."""

    card: CountingCards
    list: ListService
    state: BoardState


def move_world(settings: Settings) -> MoveWorld:
    """A Loop with Todo, Doing and In Review; Tickets ``a`` (K-1) and ``b`` (K-2) in Todo."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP)}
    state.lists = {
        "todo": list_row("todo", LOOP, 512, name="Todo"),
        "doing": list_row("doing", LOOP, 1024, name="Doing"),
        "review": list_row("review", LOOP, 2048, name="In Review"),
    }
    state.cards = {
        "a": card_row("a", "todo", LOOP).__replace__(ticket_key="K-1", title="Read the log"),
        "b": card_row("b", "todo", LOOP).__replace__(ticket_key="K-2", position=2048),
    }
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    cards = CountingCards(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=plan_views(FakePlanViews()),
        clock=lambda: NOW,
    )
    return MoveWorld(card=cards, list=ListService(checks, store), state=state)


def to(card_id: str, column: str, **more: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "card_id": card_id, "column": column, **more}


def test_move_ticket_finds_the_column_by_its_name_in_any_case_or_by_its_id(
    settings: Settings,
) -> None:
    world = move_world(settings)
    answer = _move_ticket(world, KEY, to("a", "in review"))
    assert answer == {
        "id": "a",
        "key": "K-1",
        "column": "In Review",
        "list_id": "review",
        "version": 2,
        "completed_at": None,
    }
    assert _move_ticket(world, KEY, to("a", "doing"))["column"] == "Doing"
    assert world.state.cards["a"].list_id == "doing"
    with pytest.raises(ValidationFailure) as unknown:
        _move_ticket(world, KEY, to("a", "Done"))
    assert unknown.value.details == {
        "column": "Done",
        "available": ["Todo", "Doing", "In Review"],
    }
    assert world.card.moves == 2


def test_move_ticket_answers_report_required_as_the_service_gives_it_without_another_attempt(
    settings: Settings,
) -> None:
    world = move_world(settings)
    _move_ticket(world, KEY, to("a", "Doing"))
    with pytest.raises(Conflict) as refused:
        _move_ticket(world, KEY, to("b", "Doing"))
    assert (refused.value.code, refused.value.retryable) == ("report_required", False)
    assert refused.value.message == "Report on the Tickets you took before you take another one"
    assert refused.value.details == {
        "tickets": [
            {
                "id": "a",
                "key": "K-1",
                "title": "Read the log",
                "loop_id": LOOP,
                "loop_key": "L-1",
                "taken_at": STAMP,
            }
        ],
        "report": "A comment, a wait or a completion on the Ticket since you took it",
    }
    assert world.card.moves == 2  # one for a, one for b: the refusal was not tried again
    assert (world.state.cards["b"].list_id, world.state.cards["b"].version) == ("todo", 1)
    # Putting a back in the first column is never refused, and then b may be taken.
    _move_ticket(world, KEY, to("a", "Todo"))
    assert _move_ticket(world, KEY, to("b", "Doing"))["list_id"] == "doing"


def test_move_ticket_tries_once_more_after_a_version_conflict_unless_the_version_was_given(
    settings: Settings,
) -> None:
    world = move_world(settings)

    def another_writer() -> None:
        card = world.state.cards["a"]
        world.state.cards["a"] = card.__replace__(version=card.version + 1)

    world.card.race = another_writer
    answer = _move_ticket(world, KEY, to("a", "Doing"))
    assert (answer["version"], world.card.moves) == (3, 2)
    world.card.race = another_writer
    with pytest.raises(VersionConflict):
        _move_ticket(world, KEY, to("a", "In Review", version=3))
    assert world.card.moves == 3
