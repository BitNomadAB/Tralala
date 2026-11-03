"""EventService on the in-memory board fake: events land in the caller's transaction, are replayed
in order after a sequence number, and fan out to the subscribers of their thread or ticket."""

from __future__ import annotations

import pytest

from app.core.context import ActorContext
from app.core.errors import NotFound
from app.services.boards import BoardService
from app.services.events import (
    MESSAGE_CREATED,
    SUBSCRIBER_QUEUE_SIZE,
    BoardRowCheck,
    EventService,
    serialize_event,
)
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    discussion_row,
    list_row,
    loop_row,
)

NOW = "2026-11-03T10:00:00Z"
THREAD = "thread-1"
CARD = "card-1"
ADA = ActorContext(actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=frozenset())


def board_service_is_what_events_need(service: BoardService) -> BoardRowCheck:
    """Never called: pyright proves that the BoardService wired in Services fits the check."""
    return service


def make() -> tuple[EventService, BoardState, FakeBoardUnitOfWork, FakeBoardChecks]:
    state = BoardState()
    state.loops["loop-a"] = loop_row("loop-a")
    state.lists["list-a"] = list_row("list-a", "loop-a", 1)
    state.cards[CARD] = card_row(CARD, "list-a", "loop-a")
    state.discussions[THREAD] = discussion_row(THREAD)
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    issued = iter(range(1, 1000))
    service = EventService(checks, store, clock=lambda: NOW, new_id=lambda: f"event-{next(issued)}")
    return service, state, store, checks


def test_record_returns_the_live_event_in_the_order_the_stream_sends_it() -> None:
    service, _, store, _ = make()
    with store.writer(BOARD_ID) as repos:
        event = service.record(
            repos, discussion_id=THREAD, type=MESSAGE_CREATED, payload={"n": 1}, actor=ADA
        )
    assert list(event) == [
        "seq",
        "id",
        "discussion_id",
        "type",
        "payload",
        "actor_id",
        "actor_type",
        "actor_name",
        "created_at",
    ]
    assert event == {
        "seq": 1,
        "id": "event-1",
        "discussion_id": THREAD,
        "type": MESSAGE_CREATED,
        "payload": {"n": 1},
        "actor_id": "actor-1",
        "actor_type": "user",
        "actor_name": "Ada",
        "created_at": NOW,
    }


def test_an_event_without_actor_or_payload_records_nulls_and_an_empty_payload() -> None:
    service, state, store, _ = make()
    with store.writer(BOARD_ID) as repos:
        event = service.record_card(repos, card_id=CARD, type=MESSAGE_CREATED)
    assert (event["actor_id"], event["payload"], event["card_id"]) == (None, {}, CARD)
    (stored,) = state.card_events
    assert (stored.payload_json, stored.actor_name) == ("{}", None)


def test_an_event_recorded_in_a_writer_that_raises_is_rolled_back() -> None:
    service, state, store, _ = make()
    with pytest.raises(RuntimeError), store.writer(BOARD_ID) as repos:
        service.record(repos, discussion_id=THREAD, type=MESSAGE_CREATED)
        raise RuntimeError("the change it describes failed")
    assert state.discussion_events == []


def test_replay_answers_events_after_a_sequence_number_in_order_and_limited() -> None:
    service, _, store, _ = make()
    with store.writer(BOARD_ID) as repos:
        for n in range(5):
            service.record(repos, discussion_id=THREAD, type=MESSAGE_CREATED, payload={"n": n})
    replayed = service.replay(BOARD_ID, THREAD, after=2, limit=2)
    assert [event["seq"] for event in replayed] == [3, 4]
    assert [event["payload"] for event in replayed] == [{"n": 2}, {"n": 3}]
    assert list(replayed[0]) == [
        "seq",
        "id",
        "type",
        "actor_id",
        "actor_type",
        "actor_name",
        "created_at",
        "discussion_id",
        "payload",
    ]


def test_replay_of_a_ticket_reads_only_that_tickets_events() -> None:
    service, _, store, _ = make()
    with store.writer(BOARD_ID) as repos:
        service.record_card(repos, card_id=CARD, type=MESSAGE_CREATED)
        service.record(repos, discussion_id=THREAD, type=MESSAGE_CREATED)
    assert [event["card_id"] for event in service.replay_card(BOARD_ID, CARD)] == [CARD]


def test_replay_checks_the_board_row_and_the_scope() -> None:
    service, _, _, checks = make()
    with pytest.raises(NotFound):
        service.replay(BOARD_ID, "missing")
    with pytest.raises(NotFound):
        service.replay_card(BOARD_ID, "missing")
    assert checks.calls == [("require_row", BOARD_ID), ("require_row", BOARD_ID)]


def test_publish_reaches_only_the_subscribers_of_that_thread() -> None:
    service, _, store, _ = make()
    listening = service.subscribe(BOARD_ID, THREAD)
    other = service.subscribe(BOARD_ID, "thread-2")
    ticket = service.subscribe_card(BOARD_ID, CARD)
    with store.writer(BOARD_ID) as repos:
        event = service.record(repos, discussion_id=THREAD, type=MESSAGE_CREATED)
    service.publish(BOARD_ID, event)
    assert listening.get_nowait() == event
    assert other.empty()
    assert ticket.empty()


def test_a_full_subscriber_drops_its_oldest_event_for_the_newest() -> None:
    service, _, _, _ = make()
    listening = service.subscribe(BOARD_ID, THREAD)
    for n in range(SUBSCRIBER_QUEUE_SIZE + 1):
        service.publish(BOARD_ID, {"discussion_id": THREAD, "seq": n})
    first = listening.get_nowait()
    assert first["seq"] == 1
    assert listening.qsize() == SUBSCRIBER_QUEUE_SIZE - 1


def test_unsubscribe_forgets_the_subscriber_and_the_empty_scope() -> None:
    service, _, _, _ = make()
    listening = service.subscribe(BOARD_ID, THREAD)
    assert service.subscriber_count(BOARD_ID, THREAD) == 1
    service.unsubscribe(BOARD_ID, THREAD, listening)
    assert service.subscriber_count(BOARD_ID, THREAD) == 0
    service.unsubscribe(BOARD_ID, THREAD, listening)


def test_serialize_event_parses_the_payload_and_tolerates_a_broken_one() -> None:
    parsed = serialize_event({"seq": 2, "payload_json": '{"a": 1}'})
    assert parsed == {"seq": 2, "payload": {"a": 1}}
    assert serialize_event({"seq": "x", "payload_json": "{"}) == {"seq": 0, "payload": {}}
