"""Discussions on the board itself, on the in-memory fakes: a thread with a title and no Ticket,
how the board's list narrows to them, and what the board's agents are told about one."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.errors import Conflict, ValidationFailure
from app.schemas.discussions import DiscussionCreate, DiscussionScope, DiscussionState
from tests.unit.fakes.board import BOARD_ID, FakeBoardChecks, discussion_row, loop_row
from tests.unit.test_discussion_services import ADA, CARD, THREAD, World, answer, world


def on_the_board(**fields: object) -> DiscussionCreate:
    return DiscussionCreate.model_validate({"title": "Pick a licence", "goal": "Which?", **fields})


# --- creating a thread on the board ---------------------------------------------------------------


def test_a_thread_without_a_ticket_needs_a_title_and_the_refusal_names_it() -> None:
    with pytest.raises(ValidationError) as refused:
        DiscussionCreate.model_validate({"goal": "Which licence?"})
    assert [error["loc"] for error in refused.value.errors()] == [("title",)]
    assert "title is required" in refused.value.errors()[0]["msg"]
    # On a Ticket the title stays optional, as before.
    assert DiscussionCreate.model_validate({"card_id": CARD, "goal": "x"}).title is None
    assert on_the_board().card_id is None


def test_a_thread_on_the_board_is_stored_without_a_ticket_and_without_participants() -> None:
    w = world()
    created = w.discussions.create(ADA, BOARD_ID, on_the_board())
    thread = w.state.discussions[str(created["id"])]
    assert (thread.card_id, thread.title, thread.status) == (None, "Pick a licence", "open")
    assert created["card_id"] is None
    assert (created["card_title"], created["ticket_key"], created["loop_id"]) == (None, None, None)
    assert created["participant_count"] == 0
    assert [m.content for m in w.state.discussion_messages] == ["Which?"]


def test_a_thread_on_the_board_is_logged_on_the_thread_never_on_an_empty_ticket() -> None:
    w = world()
    created = w.discussions.create(ADA, BOARD_ID, on_the_board())
    (entry,) = w.state.activity
    assert (entry.action, entry.entity_type, entry.entity_id) == (
        "discussion.created",
        "discussion",
        created["id"],
    )
    on_ticket = w.discussions.create(ADA, BOARD_ID, DiscussionCreate(card_id=CARD, goal="x"))
    assert (w.state.activity[-1].entity_type, w.state.activity[-1].entity_id) == ("card", CARD)
    assert on_ticket["card_id"] == CARD


def test_a_thread_on_the_board_needs_an_active_board() -> None:
    w = world()
    w.discussions.board_service = FakeBoardChecks(archived=frozenset({BOARD_ID}))
    with pytest.raises(Conflict) as refused:
        w.discussions.create(ADA, BOARD_ID, on_the_board())
    assert refused.value.code == "board_archived"


def test_a_thread_on_the_board_does_not_follow_any_loop_while_one_on_a_ticket_does() -> None:
    w = world()
    w.state.loops["loop-a"] = loop_row("loop-a", completed_at="2026-11-01T00:00:00Z")
    with pytest.raises(Conflict) as refused:
        w.discussions.create(ADA, BOARD_ID, DiscussionCreate(card_id=CARD, goal="x"))
    assert refused.value.code == "loop_read_only"
    assert w.discussions.create(ADA, BOARD_ID, on_the_board())["card_id"] is None


def test_a_payload_built_past_the_schema_without_a_title_is_refused_by_the_service() -> None:
    w = world()
    payload = DiscussionCreate.model_construct(
        card_id=None, title=None, goal="x", mode="manual", participant_ids=[], max_rounds=3
    )
    with pytest.raises(ValidationFailure) as refused:
        w.discussions.create(ADA, BOARD_ID, payload)
    assert refused.value.details == {"field": "title"}


# --- listing them ---------------------------------------------------------------------------------


def listed(w: World) -> None:
    """Four threads: on a Ticket or on the board, open or closed, newest first by name."""
    for name, card_id, status, at in (
        ("ticket-open", CARD, "discussing", "2026-11-04"),
        ("board-open", None, "open", "2026-11-03"),
        ("board-closed", None, "closed", "2026-11-02"),
        ("ticket-closed", CARD, "closed", "2026-11-01"),
    ):
        row = discussion_row(name, card_id=card_id, status=status)
        w.state.discussions[name] = row.__replace__(last_activity_at=at)
    del w.state.discussions[THREAD]


def test_the_list_narrows_to_the_board_or_the_tickets_and_to_open_or_closed() -> None:
    w = world()
    listed(w)
    service = w.discussions
    assert [e["id"] for e in service.list(BOARD_ID, scope="board")] == [
        "board-open",
        "board-closed",
    ]
    assert [e["id"] for e in service.list(BOARD_ID, scope="ticket")] == [
        "ticket-open",
        "ticket-closed",
    ]
    assert [e["id"] for e in service.list(BOARD_ID, state="open")] == ["ticket-open", "board-open"]
    assert [e["id"] for e in service.list(BOARD_ID, scope="board", state="closed")] == [
        "board-closed"
    ]
    assert len(service.list(BOARD_ID)) == 4


def test_the_list_filters_take_only_their_named_values() -> None:
    assert get_args(DiscussionScope) == ("board", "ticket")
    assert get_args(DiscussionState) == ("open", "closed")


# --- what the board's agents are told -------------------------------------------------------------


def test_a_round_on_the_board_names_the_board_and_the_title_instead_of_a_missing_ticket() -> None:
    w = world("alpha")
    board = w.registry.boards[BOARD_ID]
    w.registry.boards[BOARD_ID] = board.__replace__(name="Homepage", description="Our web site.")
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        card_id=None, title="Pick a licence"
    )
    w.agents.scripts = {"alpha": [answer("Fine.")]}
    w.runs.start(ADA, BOARD_ID, THREAD, rounds=1, background=False)
    (sent,) = w.agents.prompts[0]
    content = sent["content"]
    assert content.startswith("Board: Homepage\nBoard description:\nOur web site.\n")
    assert "Pick a licence" in content
    assert "Ticket: (missing)" not in content
