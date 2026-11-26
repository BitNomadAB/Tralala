"""Discussions on the board itself, on the in-memory fakes: a thread with a title and no Ticket,
how the board's list narrows to them, what the board's agents are told about one, how its opener
closes it and who opens it again, the comments a closed thread takes, and a message's pointer to a
Ticket."""

from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.schemas.discussions import (
    DiscussionCreate,
    DiscussionMessageCreate,
    DiscussionScope,
    DiscussionState,
)
from app.services.discussions import DiscussionService
from app.services.events import STATUS_CHANGED, EventService
from tests.unit.fakes.board import BOARD_ID, FakeBoardChecks, discussion_row, loop_row
from tests.unit.test_discussion_services import (
    ADA,
    BOT,
    CARD,
    NOW,
    THREAD,
    World,
    answer,
    entries,
    run_row,
    world,
)


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


# --- closing and opening again --------------------------------------------------------------------

GRACE = ActorContext(
    actor_id="actor-2", actor_type="user", actor_name="Grace", scopes=frozenset(ADA.scopes)
)
OTHER_KEY = ActorContext(
    actor_id="other-key", actor_type="agent", actor_name="Other", scopes=frozenset(ADA.scopes)
)


def with_events(w: World) -> EventService:
    events = EventService(FakeBoardChecks(), w.store, clock=lambda: NOW)
    w.discussions.events = events
    return events


def closed(w: World) -> None:
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        status="closed", closed_at=NOW, closed_by_actor_id=ADA.actor_id
    )


def test_only_the_opener_closes_a_thread_not_even_another_person() -> None:
    w = world()
    for someone in (GRACE, BOT):
        with pytest.raises(Forbidden) as refused:
            w.discussions.close(someone, BOARD_ID, THREAD)
        assert refused.value.code == "not_opener"
    answered = w.discussions.close(ADA, BOARD_ID, THREAD)
    thread = w.state.discussions[THREAD]
    assert (thread.status, thread.closed_at, thread.closed_by_actor_id) == (
        "closed",
        NOW,
        ADA.actor_id,
    )
    assert (answered["status"], answered["closed_at"]) == ("closed", NOW)


def test_a_key_that_opened_a_thread_closes_it_and_closing_needs_the_write_scope() -> None:
    w = world()
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        created_by_actor_id=BOT.actor_id, created_by_type="agent"
    )
    reader = BOT.__replace__(scopes=frozenset({"discussions:read"}))
    with pytest.raises(Forbidden) as refused:
        w.discussions.close(reader, BOARD_ID, THREAD)
    assert refused.value.details == {"required_scope": "discussions:write"}
    assert w.discussions.close(BOT, BOARD_ID, THREAD)["status"] == "closed"


def test_a_closed_or_cancelled_thread_is_not_closed_again_and_a_running_one_waits() -> None:
    w = world("alpha")
    w.state.runs["run-1"] = run_row(status="running")
    with pytest.raises(Conflict, match="run is still active"):
        w.discussions.close(ADA, BOARD_ID, THREAD)
    del w.state.runs["run-1"]
    for status in ("closed", "cancelled"):
        w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(status=status)
        with pytest.raises(Conflict) as refused:
            w.discussions.close(ADA, BOARD_ID, THREAD)
        assert refused.value.details == {"status": status}
    with pytest.raises(NotFound):
        w.discussions.close(ADA, BOARD_ID, "missing")


def test_closing_and_opening_again_are_logged_and_announced_as_status_changes() -> None:
    w = world()
    events = with_events(w)
    listener = events.subscribe(BOARD_ID, THREAD)
    w.discussions.close(ADA, BOARD_ID, THREAD)
    w.discussions.reopen(ADA, BOARD_ID, THREAD)
    assert [(a.action, a.entity_type, a.entity_id) for a in w.state.activity] == [
        ("discussion.closed", "card", CARD),
        ("discussion.reopened", "card", CARD),
    ]
    stored = [(e.type, json.loads(e.payload_json)["status"]) for e in w.state.discussion_events]
    assert stored == [(STATUS_CHANGED, "closed"), (STATUS_CHANGED, "discussing")]
    assert json.loads(w.state.discussion_events[0].payload_json)["closed_at"] == NOW
    assert listener.qsize() == 2
    # A thread on the board is logged on the thread itself.
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(card_id=None)
    w.discussions.close(ADA, BOARD_ID, THREAD)
    assert (w.state.activity[-1].entity_type, w.state.activity[-1].entity_id) == (
        "discussion",
        THREAD,
    )


def test_the_opener_or_a_person_opens_a_closed_thread_again_but_not_another_key() -> None:
    w = world()
    closed(w)
    with pytest.raises(Forbidden) as refused:
        w.discussions.reopen(OTHER_KEY, BOARD_ID, THREAD)
    assert refused.value.code == "not_opener"
    answered = w.discussions.reopen(GRACE, BOARD_ID, THREAD)
    thread = w.state.discussions[THREAD]
    assert (thread.status, thread.closed_at, thread.closed_by_actor_id) == (
        "discussing",
        None,
        None,
    )
    assert (answered["status"], answered["closed_at"]) == ("discussing", None)
    with pytest.raises(Conflict) as again:
        w.discussions.reopen(ADA, BOARD_ID, THREAD)
    assert again.value.details == {"status": "discussing"}
    # The key that opened a thread opens it again.
    w.state.discussions[THREAD] = w.state.discussions[THREAD].__replace__(
        created_by_actor_id=OTHER_KEY.actor_id, status="closed"
    )
    assert w.discussions.reopen(OTHER_KEY, BOARD_ID, THREAD)["status"] == "discussing"


def test_a_thread_on_a_ticket_of_a_read_only_loop_is_neither_closed_nor_opened_again() -> None:
    w = world()
    w.state.loops["loop-a"] = loop_row("loop-a", completed_at="2026-11-01T00:00:00Z")
    with pytest.raises(Conflict) as refused:
        w.discussions.close(ADA, BOARD_ID, THREAD)
    assert refused.value.code == "loop_read_only"
    closed(w)
    with pytest.raises(Conflict) as refused:
        w.discussions.reopen(ADA, BOARD_ID, THREAD)
    assert refused.value.code == "loop_read_only"


# --- a closed thread takes comments ---------------------------------------------------------------


def test_a_comment_in_a_closed_thread_is_kept_after_the_close_and_starts_no_round() -> None:
    w = world("alpha", mode="roundtable")
    closed(w)
    w.agents.scripts = {"alpha": [answer("Never asked.")]}
    detail = w.discussions.add_message(
        ADA, BOARD_ID, THREAD, DiscussionMessageCreate(content="@alpha one more thing")
    )
    (stored,) = w.state.discussion_messages
    assert stored.after_closed == 1
    assert w.state.discussions[THREAD].status == "closed"
    assert (detail["auto_run"], w.state.runs, w.agents.calls) == ("thread_closed", {}, [])
    (message,) = entries(detail["messages"])
    assert message["after_closed"] is True
    # A key's comment starts nothing either, and says why.
    keyed = w.discussions.add_message(BOT, BOARD_ID, THREAD, DiscussionMessageCreate(content="x"))
    assert keyed["auto_run"] == "thread_closed"


def test_a_closed_thread_starts_no_run_and_takes_no_review() -> None:
    w = world("alpha")
    closed(w)
    with pytest.raises(Conflict) as refused:
        w.runs.start(ADA, BOARD_ID, THREAD, background=False)
    assert refused.value.details == {"status": "closed"}
    with pytest.raises(Conflict) as review:
        w.discussions.review(ADA, BOARD_ID, THREAD, decision="approve")
    assert review.value.details == {"status": "closed"}


def test_a_message_in_an_open_thread_is_not_after_the_close() -> None:
    w = world()
    detail = w.discussions.add_message(ADA, BOARD_ID, THREAD, DiscussionMessageCreate(content="x"))
    (message,) = entries(detail["messages"])
    assert (message["after_closed"], message["ref_ticket"]) == (False, None)
    assert "ref_card_id" not in message


# --- a message points at a Ticket -----------------------------------------------------------------


def test_a_message_points_at_a_ticket_by_its_id_or_its_key() -> None:
    w = world()
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(ticket_key="L-1-001", title="Licence")
    for reference in ("L-1-001", CARD):
        w.discussions.add_message(
            ADA, BOARD_ID, THREAD, DiscussionMessageCreate(content="See this.", ticket=reference)
        )
    assert [m.ref_card_id for m in w.state.discussion_messages] == [CARD, CARD]
    detail = w.discussions.get(BOARD_ID, THREAD)
    assert [m["ref_ticket"] for m in entries(detail["messages"])] == [
        {"card_id": CARD, "ticket_key": "L-1-001", "title": "Licence", "loop_id": "loop-a"}
    ] * 2


def test_a_message_that_points_at_an_unknown_ticket_is_refused() -> None:
    w = world()
    with pytest.raises(ValidationFailure) as refused:
        w.discussions.add_message(
            ADA, BOARD_ID, THREAD, DiscussionMessageCreate(content="x", ticket="NOPE-1")
        )
    assert refused.value.details == {"field": "ticket", "ticket": "NOPE-1"}
    assert w.state.discussion_messages == []


def test_nothing_deletes_a_thread_or_a_message() -> None:
    assert [name for name in dir(DiscussionService) if "delete" in name or "remove" in name] == []
