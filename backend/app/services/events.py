"""Discussion and ticket events: a durable scoped log plus an in-process fan-out.

Every event is written in the same transaction as the change it describes and only then handed to
subscribers, so a client that reconnects with `Last-Event-ID` can replay everything it missed and a
dropped publish can never lose history. No broker is involved: subscribers are in-process queues.

Two scopes exist: a discussion thread (`discussion_events`) and a ticket (`card_events`, used by
agent mentions in comments). The scope is derived from the event row itself, so one publish path
serves both.
"""

from __future__ import annotations

import contextlib
import json
import queue
from collections.abc import Callable, Mapping
from threading import Lock
from typing import Protocol, TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import NotFound
from ..db.generated.board import CardEventsRow, DiscussionEventsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.events import NewEvent

MESSAGE_CREATED = "message_created"
AGENT_STARTED = "agent_started"
AGENT_COMPLETED = "agent_completed"
AGENT_FAILED = "agent_failed"
VOTE_RECORDED = "vote_recorded"
CONSENSUS_PROPOSED = "consensus_proposed"
STATUS_CHANGED = "discussion_status_changed"
HUMAN_REVIEW_COMPLETED = "human_review_completed"
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
ROUND_COMPLETED = "round_completed"

EVENT_TYPES = (
    MESSAGE_CREATED,
    AGENT_STARTED,
    AGENT_COMPLETED,
    AGENT_FAILED,
    VOTE_RECORDED,
    CONSENSUS_PROPOSED,
    STATUS_CHANGED,
    HUMAN_REVIEW_COMPLETED,
    RUN_STARTED,
    RUN_FINISHED,
    ROUND_COMPLETED,
)

SUBSCRIBER_QUEUE_SIZE = 256

# Scope kinds; the tuple key is (board id, scope, scope id).
DISCUSSION = "discussion"
CARD = "card"

Event = dict[str, object]
"""An event as it is published and replayed: the JSON the streams and replay routes send."""

Subscriber = queue.Queue[Event]


class BoardRowCheck(Protocol):
    def require_row(self, board_id: str) -> object: ...


class _Actor(TypedDict):
    actor_id: str | None
    actor_type: str | None
    actor_name: str | None


def _actor_fields(actor: ActorContext | None) -> _Actor:
    if actor is None:
        return {"actor_id": None, "actor_type": None, "actor_name": None}
    return {
        "actor_id": actor.actor_id,
        "actor_type": actor.actor_type,
        "actor_name": actor.actor_name,
    }


def _new_id() -> str:
    return str(uuid4())


class EventService:
    """Records discussion and ticket events durably and streams them to live subscribers."""

    def __init__(
        self,
        board_service: BoardRowCheck,
        store: BoardUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.board_service = board_service
        self.store = store
        self._clock = clock
        self._new_id = new_id
        self._subscribers: dict[tuple[str, str, str], set[Subscriber]] = {}
        self._lock = Lock()

    # --- recording -----------------------------------------------------------

    def _new_event(
        self, type: str, payload: Mapping[str, object] | None, actor: ActorContext | None
    ) -> NewEvent:
        actor_fields = _actor_fields(actor)
        return {
            "id": self._new_id(),
            "type": type,
            "payload_json": json.dumps(dict(payload or {})),
            "actor_id": actor_fields["actor_id"],
            "actor_type": actor_fields["actor_type"],
            "actor_name": actor_fields["actor_name"],
            "created_at": self._clock(),
        }

    def record(
        self,
        repos: BoardRepositories,
        *,
        discussion_id: str,
        type: str,
        payload: Mapping[str, object] | None = None,
        actor: ActorContext | None = None,
    ) -> Event:
        """Insert one event inside the caller's transaction and return it for publishing."""
        event = self._new_event(type, payload, actor)
        seq = repos.events.add_discussion_event(discussion_id, event)
        return _published(seq, event, "discussion_id", discussion_id, payload)

    def record_card(
        self,
        repos: BoardRepositories,
        *,
        card_id: str,
        type: str,
        payload: Mapping[str, object] | None = None,
        actor: ActorContext | None = None,
    ) -> Event:
        """Insert one ticket event; agent mention work is announced the same way threads are."""
        event = self._new_event(type, payload, actor)
        seq = repos.events.add_card_event(card_id, event)
        return _published(seq, event, "card_id", card_id, payload)

    # --- fan-out -------------------------------------------------------------

    @staticmethod
    def _key(board_id: str, event: Event) -> tuple[str, str, str]:
        if event.get("discussion_id"):
            return (board_id, DISCUSSION, str(event["discussion_id"]))
        return (board_id, CARD, str(event["card_id"]))

    def publish(self, board_id: str, event: Event) -> None:
        with self._lock:
            targets = list(self._subscribers.get(self._key(board_id, event), ()))
        for target in targets:
            try:
                target.put_nowait(event)
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    target.get_nowait()
                with contextlib.suppress(queue.Full):
                    target.put_nowait(event)

    def subscribe(self, board_id: str, discussion_id: str) -> Subscriber:
        return self._subscribe((board_id, DISCUSSION, discussion_id))

    def subscribe_card(self, board_id: str, card_id: str) -> Subscriber:
        return self._subscribe((board_id, CARD, card_id))

    def _subscribe(self, key: tuple[str, str, str]) -> Subscriber:
        target: Subscriber = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(target)
        return target

    def unsubscribe(self, board_id: str, discussion_id: str, target: Subscriber) -> None:
        self._unsubscribe((board_id, DISCUSSION, discussion_id), target)

    def unsubscribe_card(self, board_id: str, card_id: str, target: Subscriber) -> None:
        self._unsubscribe((board_id, CARD, card_id), target)

    def _unsubscribe(self, key: tuple[str, str, str], target: Subscriber) -> None:
        with self._lock:
            listeners = self._subscribers.get(key)
            if not listeners:
                return
            listeners.discard(target)
            if not listeners:
                self._subscribers.pop(key, None)

    def subscriber_count(self, board_id: str, discussion_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get((board_id, DISCUSSION, discussion_id), ()))

    # --- replay --------------------------------------------------------------

    def ensure_discussion(self, board_id: str, discussion_id: str) -> None:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            found = repos.events.discussion_exists(discussion_id)
        if not found:
            raise NotFound("Discussion not found")

    def ensure_card(self, board_id: str, card_id: str) -> None:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            found = repos.cards.get(card_id) is not None
        if not found:
            raise NotFound("Card not found")

    def replay(
        self,
        board_id: str,
        discussion_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[Event]:
        self.ensure_discussion(board_id, discussion_id)
        with self.store.reader(board_id) as repos:
            rows = repos.events.discussion_events(discussion_id, after=after, limit=limit)
        return [_replayed(row, "discussion_id", row.discussion_id) for row in rows]

    def replay_card(
        self,
        board_id: str,
        card_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[Event]:
        self.ensure_card(board_id, card_id)
        with self.store.reader(board_id) as repos:
            rows = repos.events.card_events(card_id, after=after, limit=limit)
        return [_replayed(row, "card_id", row.card_id) for row in rows]

    def shutdown(self) -> None:
        with self._lock:
            self._subscribers.clear()


def _published(
    seq: int, event: NewEvent, column: str, scope_id: str, payload: Mapping[str, object] | None
) -> Event:
    """The live event, keys in the order the streams have always sent them."""
    return {
        "seq": seq,
        "id": event["id"],
        column: scope_id,
        "type": event["type"],
        "payload": dict(payload or {}),
        "actor_id": event["actor_id"],
        "actor_type": event["actor_type"],
        "actor_name": event["actor_name"],
        "created_at": event["created_at"],
    }


def _replayed(row: DiscussionEventsRow | CardEventsRow, column: str, scope_id: str) -> Event:
    """A stored event, keys in the order the replay routes have always sent them."""
    return serialize_event(
        {
            "seq": row.seq,
            "id": row.id,
            "type": row.type,
            "payload_json": row.payload_json,
            "actor_id": row.actor_id,
            "actor_type": row.actor_type,
            "actor_name": row.actor_name,
            "created_at": row.created_at,
            column: scope_id,
        }
    )


def serialize_event(row: Mapping[str, object]) -> Event:
    """A stored event row as JSON, with ``payload_json`` parsed into ``payload`` (or ``{}``)."""
    entry = dict(row)
    raw = entry.pop("payload_json", "{}")
    try:
        payload: object = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        payload = {}
    entry["payload"] = payload
    seq = entry.get("seq")
    entry["seq"] = seq if isinstance(seq, int) else 0
    return entry


__all__ = [
    "AGENT_COMPLETED",
    "AGENT_FAILED",
    "AGENT_STARTED",
    "CARD",
    "CONSENSUS_PROPOSED",
    "DISCUSSION",
    "EVENT_TYPES",
    "HUMAN_REVIEW_COMPLETED",
    "MESSAGE_CREATED",
    "ROUND_COMPLETED",
    "RUN_FINISHED",
    "RUN_STARTED",
    "STATUS_CHANGED",
    "VOTE_RECORDED",
    "EventService",
    "serialize_event",
]
