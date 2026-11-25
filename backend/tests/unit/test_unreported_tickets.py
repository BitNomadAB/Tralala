"""The Tickets an actor has taken and not reported on since (``CardRepository.unreported_by``),
and the same for the listed cards and every key at once (``CardRepository.unreported_since``), on
the fake board: what counts as taken, what counts as a report, and the answers.

Taken is a ``card.moved`` by the actor on an open, unarchived card of an open Loop that is not in
the Loop's first column; a report is the actor's comment or wait at the first move's second or
later. For the batched read a key is an actor whose move was logged as ``agent``, each key is held
to its own first move, and the card answers the earliest key still owed a report. The SQL
statements in ``app/repositories/sql/cards.py`` answer the same rules; dbgen compiles them against
the schema.
"""

from __future__ import annotations

from collections.abc import Sequence

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


def log(
    state: BoardState,
    action: str,
    card_id: str,
    *,
    actor_id: str,
    at: str,
    actor_type: str = "agent",
) -> None:
    entry_id = f"e-{len(state.activity) + 1}"
    state.activity.append(
        activity_row(
            entry_id, action, card_id, actor_id=actor_id, actor_type=actor_type, timestamp=at
        )
    )


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


# --- the listed cards, every key at once (unreported_since) ---------------------------------------


def since(state: BoardState, card_ids: Sequence[str] = ("c1",)) -> dict[str, str | None]:
    cards: CardRepository = FakeCardRepository(state)
    return cards.unreported_since(card_ids)


def test_a_keys_move_without_a_report_marks_the_card_with_the_move() -> None:
    state = board()
    state.cards["c2"] = card_row("c2", "doing", LOOP)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    # Every requested id is a key: one nobody took, and one the board does not have, are None.
    assert since(state, ["c1", "c2", "missing"]) == {"c1": MOVED, "c2": None, "missing": None}
    assert since(state, []) == {}


@pytest.mark.parametrize("at", [LATER, MOVED], ids=["after the move", "in its second"])
def test_the_keys_comment_since_the_move_takes_the_mark_away(at: str) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    comment(state, "c1", actor_id=WORKER, at=at)
    assert since(state) == {"c1": None}


def test_a_comment_before_the_move_leaves_the_mark() -> None:
    state = board()
    comment(state, "c1", actor_id=WORKER, at=EARLIER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert since(state) == {"c1": MOVED}


@pytest.mark.parametrize("cleared", [False, True], ids=["still waiting", "cleared by a person"])
def test_the_keys_wait_since_the_move_takes_the_mark_away(cleared: bool) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.wait_set", "c1", actor_id=WORKER, at=LATER)
    if cleared:  # the log keeps the wait a person cleared
        log(state, "card.wait_cleared", "c1", actor_id=PERSON, at=LATER, actor_type="user")
    assert since(state) == {"c1": None}
    # A wait set before the move is no report on it.
    state = board()
    log(state, "card.wait_set", "c1", actor_id=WORKER, at=EARLIER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert since(state) == {"c1": MOVED}


def test_a_persons_move_never_marks_the_card() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=PERSON, at=MOVED, actor_type="user")
    assert since(state) == {"c1": None}
    # Nor does a person's later move of a card a key took: the key still owes its report.
    log(state, "card.moved", "c1", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c1", actor_id=PERSON, at="2026-11-25T10:09:00Z", actor_type="user")
    assert since(state) == {"c1": LATER}


def test_two_keys_without_a_report_give_the_earliest_move_and_each_reports_for_itself() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=OTHER, at=LATER)
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    assert since(state) == {"c1": MOVED}
    # The second key's comment is no report for the first, which still marks the card.
    comment(state, "c1", actor_id=OTHER, at="2026-11-25T10:06:00Z")
    assert since(state) == {"c1": MOVED}
    # The first key's comment after its own move reports for it; the second key has reported too.
    comment(state, "c1", actor_id=WORKER, at=MOVED)
    assert since(state) == {"c1": None}


def test_each_key_is_held_to_its_own_first_move() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=EARLIER)
    comment(state, "c1", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c1", actor_id=OTHER, at=LATER)
    # The first key reported after its move; the second moved later and has not.
    assert since(state) == {"c1": LATER}
    log(state, "card.wait_set", "c1", actor_id=OTHER, at=MOVED)  # before the second key's move
    assert since(state) == {"c1": LATER}


def test_a_card_in_the_first_column_is_not_marked() -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    state.cards["c1"] = state.cards["c1"].__replace__(list_id="todo")
    assert since(state) == {"c1": None}


@pytest.mark.parametrize("column", ["completed_at", "archived_at"])
def test_a_completed_or_archived_card_is_not_marked(column: str) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    card = state.cards["c1"]
    if column == "completed_at":
        state.cards["c1"] = card.__replace__(completed_at=LATER)
    else:
        state.cards["c1"] = card.__replace__(archived_at=LATER)
    assert since(state) == {"c1": None}


@pytest.mark.parametrize("column", ["completed_at", "cancelled_at", "archived_at"])
def test_a_card_of_a_completed_cancelled_or_archived_loop_is_not_marked(column: str) -> None:
    state = board()
    log(state, "card.moved", "c1", actor_id=WORKER, at=MOVED)
    match column:
        case "completed_at":
            state.loops[LOOP] = loop_row(LOOP, stage="completed", completed_at=LATER)
        case "cancelled_at":
            state.loops[LOOP] = loop_row(LOOP, stage="cancelled", cancelled_at=LATER)
        case _:
            state.loops[LOOP] = loop_row(LOOP, archived_at=LATER)
    assert since(state) == {"c1": None}


def test_the_batched_read_agrees_with_the_read_for_each_key() -> None:
    """For every card, the earliest ``taken_at`` among the keys whose ``unreported_by`` names it."""
    state = board()
    for card_id, list_id in (("c2", "doing"), ("c3", "done"), ("c4", "todo"), ("c5", "done")):
        state.cards[card_id] = card_row(card_id, list_id, LOOP)
    log(state, "card.moved", "c1", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c1", actor_id=OTHER, at=MOVED)
    log(state, "card.moved", "c2", actor_id=WORKER, at=MOVED)
    comment(state, "c2", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c3", actor_id=OTHER, at=EARLIER)
    log(state, "card.wait_set", "c3", actor_id=WORKER, at=LATER)
    log(state, "card.moved", "c4", actor_id=WORKER, at=MOVED)
    log(state, "card.moved", "c5", actor_id=PERSON, at=MOVED, actor_type="user")
    ids = sorted(state.cards)
    expected: dict[str, str | None] = dict.fromkeys(ids, None)
    for actor_id in (WORKER, OTHER):
        for ticket in unreported(state, actor_id):
            known = expected[ticket.card.id]
            expected[ticket.card.id] = (
                ticket.taken_at if known is None else min(known, ticket.taken_at)
            )
    assert expected == {"c1": MOVED, "c2": None, "c3": EARLIER, "c4": None, "c5": None}
    assert since(state, ids) == expected
