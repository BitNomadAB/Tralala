"""The Tickets an actor has taken and not reported on since (``CardRepository.unreported_by``),
on the fake board: what counts as taken, what counts as a report, and the order of the answer.

Taken is a ``card.moved`` by the actor on an open, unarchived card of an open Loop that is not in
the Loop's first column; a report is the actor's comment or wait at the first move's second or
later. The SQL statement in ``app/repositories/sql/cards.py`` answers the same rules; dbgen
compiles it against the schema.
"""

from __future__ import annotations

import pytest

from app.repositories.cards import CardRepository, UnreportedTicket
from tests.unit.fakes.board import (
    BoardState,
    FakeCardRepository,
    activity_row,
    card_row,
    comment_row,
    list_row,
    loop_row,
)

LOOP = "loop-a"
WORKER = "agent-1"
OTHER = "agent-2"
PERSON = "actor-1"
EARLIER = "2026-11-25T09:55:00Z"
MOVED = "2026-11-25T10:00:00Z"
LATER = "2026-11-25T10:05:00Z"


def board() -> BoardState:
    """One Loop with three columns and card ``c1`` in the middle one."""
    state = BoardState()
    state.loops[LOOP] = loop_row(LOOP)
    for list_id, position in (("todo", 1024), ("doing", 2048), ("done", 3072)):
        state.lists[list_id] = list_row(list_id, LOOP, position)
    state.cards["c1"] = card_row("c1", "doing", LOOP)
    return state


def log(state: BoardState, action: str, card_id: str, *, actor_id: str, at: str) -> None:
    entry_id = f"e-{len(state.activity) + 1}"
    state.activity.append(activity_row(entry_id, action, card_id, actor_id=actor_id, timestamp=at))


def comment(state: BoardState, card_id: str, *, actor_id: str, at: str) -> None:
    comment_id = f"m-{len(state.comments) + 1}"
    state.comments[comment_id] = comment_row(
        comment_id, card_id, actor_id=actor_id, created_at=at
    )


def unreported(state: BoardState, actor_id: str = WORKER) -> list[UnreportedTicket]:
    cards: CardRepository = FakeCardRepository(state)
    return cards.unreported_by(actor_id)


def taken(state: BoardState, actor_id: str = WORKER) -> list[tuple[str, str]]:
    return [(ticket.card.id, ticket.taken_at) for ticket in unreported(state, actor_id)]


def test_a_card_the_actor_moved_without_a_report_is_answered_with_its_loop() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert unreported(state) == [
        UnreportedTicket(
            card=state.cards["c1"],
            loop_id=LOOP,
            loop_key="L-1",
            loop_name=f"Loop {LOOP}",
            taken_at=MOVED,
        )
    ]


def test_a_comment_after_the_move_is_a_report() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    comment(state, "c1", actor_id=WORKER, at=LATER)
    assert unreported(state) == []


def test_a_comment_in_the_second_of_the_move_is_a_report() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    comment(state, "c1", actor_id=WORKER, at=MOVED)
    assert unreported(state) == []


def test_a_comment_before_the_move_is_not_a_report() -> None:
    state = board()
    comment(state, "c1", actor_id=WORKER, at=EARLIER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert taken(state) == [("c1", MOVED)]


@pytest.mark.parametrize("set_at", [LATER, MOVED], ids=["after the move", "in its second"])
@pytest.mark.parametrize("cleared", [False, True], ids=["still waiting", "cleared by a person"])
def test_a_wait_set_since_the_move_is_a_report_even_after_a_person_cleared_it(
    set_at: str, cleared: bool
) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.wait_set", "c1", actor_id=WORKER, at=set_at)
    state.cards["c1"] = state.cards["c1"].__replace__(
        waiting_for="decision",
        waiting_reason="Which one?",
        waiting_set_at=set_at,
        waiting_set_by=WORKER,
    )
    if cleared:
        # clear_wait empties the card's wait, waiting_set_by included; the log keeps the wait.
        log(state, "card.wait_cleared", "c1", actor_id=PERSON, at="2026-11-25T10:09:00Z")
        state.cards["c1"] = state.cards["c1"].__replace__(
            waiting_for="nothing", waiting_reason="", waiting_set_at=None, waiting_set_by=None
        )
    assert unreported(state) == []


def test_a_wait_set_before_the_move_is_not_a_report() -> None:
    state = board()
    log(state, "card.wait_set", "c1", actor_id=WORKER, at=EARLIER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert taken(state) == [("c1", MOVED)]


@pytest.mark.parametrize("column", ["completed_at", "archived_at"])
def test_a_completed_or_archived_card_is_not_taken(column: str) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    card = state.cards["c1"]
    if column == "completed_at":
        state.cards["c1"] = card.__replace__(completed_at=LATER)
    else:
        state.cards["c1"] = card.__replace__(archived_at=LATER)
    assert unreported(state) == []


def test_a_card_back_in_the_first_column_is_not_taken() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c1", actor_id=PERSON, at=LATER)
    state.cards["c1"] = state.cards["c1"].__replace__(list_id="todo")
    assert unreported(state) == []


def test_the_first_column_is_the_first_unarchived_list_by_position_and_id() -> None:
    state = BoardState()
    state.loops[LOOP] = loop_row(LOOP)
    state.lists["gone"] = list_row("gone", LOOP, 0, archived_at=EARLIER)
    state.lists["b-next"] = list_row("b-next", LOOP, 1024)
    state.lists["a-first"] = list_row("a-first", LOOP, 1024)
    for card_id, list_id in (("c1", "a-first"), ("c2", "b-next"), ("c3", "gone")):
        state.cards[card_id] = card_row(card_id, list_id, LOOP)
        log(state, "card.moved", card_id, actor_id=WORKER, at=MOVED)
    assert taken(state) == [("c2", MOVED), ("c3", MOVED)]


def test_a_loop_without_an_unarchived_list_has_no_first_column() -> None:
    state = board()
    state.lists = {
        list_id: row.__replace__(archived_at=EARLIER) for list_id, row in state.lists.items()
    }
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert taken(state) == [("c1", MOVED)]


@pytest.mark.parametrize("column", ["completed_at", "cancelled_at", "archived_at"])
def test_a_card_of_a_completed_cancelled_or_archived_loop_is_not_taken(column: str) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    match column:
        case "completed_at":
            state.loops[LOOP] = loop_row(LOOP, stage="completed", completed_at=LATER)
        case "cancelled_at":
            state.loops[LOOP] = loop_row(LOOP, stage="cancelled", cancelled_at=LATER)
        case _:
            state.loops[LOOP] = loop_row(LOOP, archived_at=LATER)
    assert unreported(state) == []


def test_another_actors_move_does_not_make_the_card_taken() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=OTHER, at=MOVED)
    assert unreported(state) == []
    assert taken(state, OTHER) == [("c1", MOVED)]


def test_another_actors_comment_or_wait_is_not_a_report() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    comment(state, "c1", actor_id=OTHER, at=LATER)
    log(state, "card.wait_set", "c1", actor_id=PERSON, at=LATER)
    assert taken(state) == [("c1", MOVED)]


def test_a_report_on_another_card_is_not_a_report_on_this_one() -> None:
    state = board()
    state.cards["c2"] = card_row("c2", "doing", LOOP)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    comment(state, "c2", actor_id=WORKER, at=LATER)
    log(state, "card.wait_set", "c2", actor_id=WORKER, at=LATER)
    assert taken(state) == [("c1", MOVED)]


def test_several_moves_give_the_first_as_taken_at() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c1", actor_id=WORKER, at="2026-11-25T10:09:00Z")
    assert taken(state) == [("c1", MOVED)]


def test_a_report_after_the_first_move_counts_although_a_later_move_followed() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=EARLIER)
    comment(state, "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c1", actor_id=WORKER, at=LATER)
    assert unreported(state) == []


def test_the_answer_covers_every_loop_by_taken_at_then_card_id() -> None:
    state = board()
    state.loops["loop-b"] = loop_row("loop-b").__replace__(sequence=2, key="L-2")
    state.lists["b-todo"] = list_row("b-todo", "loop-b", 1024)
    state.lists["b-doing"] = list_row("b-doing", "loop-b", 2048)
    state.cards["c2"] = card_row("c2", "b-doing", "loop-b")
    state.cards["c0"] = card_row("c0", "done", LOOP)
    log(state, "card.moved", "c1", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c2", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c0", actor_id=WORKER, at=LATER)
    answer = unreported(state)
    assert [(ticket.card.id, ticket.taken_at) for ticket in answer] == [
        ("c2", MOVED),
        ("c0", LATER),
        ("c1", LATER),
    ]
    assert [(ticket.loop_id, ticket.loop_key) for ticket in answer] == [
        ("loop-b", "L-2"),
        (LOOP, "L-1"),
        (LOOP, "L-1"),
    ]
