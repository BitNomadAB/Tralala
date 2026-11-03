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
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core import sql
from ..core.context import ActorContext
from ..core.errors import NotFound
from ..storage.board_db import BoardDatabaseManager
from ..storage.sqlite import utcnow
from .boards import BoardService

# The event tables and their scope columns; the names are formatted into SQL text (core/sql.py).
_EVENT_TABLES = ("discussion_events", "card_events")
_SCOPE_COLUMNS = ("discussion_id", "card_id")

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


class EventService:
    """Records discussion and ticket events durably and streams them to live subscribers."""

    def __init__(self, board_service: BoardService, *, boards: BoardDatabaseManager) -> None:
        self.board_service = board_service
        self.boards = boards
        self._subscribers: dict[tuple[str, str, str], set[queue.Queue]] = {}
        self._lock = Lock()

    # --- recording -----------------------------------------------------------

    def record(
        self,
        conn: Any,
        *,
        discussion_id: str,
        type: str,
        payload: dict[str, Any] | None = None,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        """Insert one event inside the caller's transaction and return it for publishing."""
        return self._insert(conn, "discussion_events", discussion_id, type, payload, actor)

    def record_card(
        self,
        conn: Any,
        *,
        card_id: str,
        type: str,
        payload: dict[str, Any] | None = None,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        """Insert one ticket event; agent mention work is announced the same way threads are."""
        return self._insert(conn, "card_events", card_id, type, payload, actor)

    def _insert(
        self,
        conn: Any,
        table: str,
        scope_id: str,
        type: str,
        payload: dict[str, Any] | None,
        actor: ActorContext | None,
    ) -> dict[str, Any]:
        table = sql.identifier(table, _EVENT_TABLES)
        column = sql.identifier(
            "discussion_id" if table == "discussion_events" else "card_id", _SCOPE_COLUMNS
        )
        event_id = str(uuid4())
        now = utcnow()
        result = conn.execute(
            text(
                f"INSERT INTO {table}"  # noqa: S608 - from _EVENT_TABLES and _SCOPE_COLUMNS
                f" (id, {column}, type, payload_json, actor_id, actor_type, actor_name,"
                "  created_at)"
                " VALUES (:id, :scope_id, :type, :payload, :actor_id, :actor_type,"
                "         :actor_name, :now)"
            ),
            {
                "id": event_id,
                "scope_id": scope_id,
                "type": type,
                "payload": json.dumps(payload or {}),
                "actor_id": actor.actor_id if actor else None,
                "actor_type": actor.actor_type if actor else None,
                "actor_name": actor.actor_name if actor else None,
                "now": now,
            },
        )
        return {
            "seq": int(result.lastrowid or 0),
            "id": event_id,
            column: scope_id,
            "type": type,
            "payload": payload or {},
            "actor_id": actor.actor_id if actor else None,
            "actor_type": actor.actor_type if actor else None,
            "actor_name": actor.actor_name if actor else None,
            "created_at": now,
        }

    # --- fan-out -------------------------------------------------------------

    @staticmethod
    def _key(board_id: str, event: dict[str, Any]) -> tuple[str, str, str]:
        if event.get("discussion_id"):
            return (board_id, DISCUSSION, str(event["discussion_id"]))
        return (board_id, CARD, str(event["card_id"]))

    def publish(self, board_id: str, event: dict[str, Any]) -> None:
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

    def subscribe(self, board_id: str, discussion_id: str) -> queue.Queue:
        return self._subscribe((board_id, DISCUSSION, discussion_id))

    def subscribe_card(self, board_id: str, card_id: str) -> queue.Queue:
        return self._subscribe((board_id, CARD, card_id))

    def _subscribe(self, key: tuple[str, str, str]) -> queue.Queue:
        target: queue.Queue = queue.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(target)
        return target

    def unsubscribe(self, board_id: str, discussion_id: str, target: queue.Queue) -> None:
        self._unsubscribe((board_id, DISCUSSION, discussion_id), target)

    def unsubscribe_card(self, board_id: str, card_id: str, target: queue.Queue) -> None:
        self._unsubscribe((board_id, CARD, card_id), target)

    def _unsubscribe(self, key: tuple[str, str, str], target: queue.Queue) -> None:
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
        with self.boards.reader(board_id) as conn:
            row = conn.execute(
                text("SELECT 1 FROM discussion_threads WHERE id = :id"), {"id": discussion_id}
            ).first()
        if row is None:
            raise NotFound("Discussion not found")

    def ensure_card(self, board_id: str, card_id: str) -> None:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            row = conn.execute(text("SELECT 1 FROM cards WHERE id = :id"), {"id": card_id}).first()
        if row is None:
            raise NotFound("Card not found")

    def replay(
        self,
        board_id: str,
        discussion_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.ensure_discussion(board_id, discussion_id)
        return self._replay(
            board_id, "discussion_events", "discussion_id", discussion_id, after=after, limit=limit
        )

    def replay_card(
        self,
        board_id: str,
        card_id: str,
        *,
        after: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.ensure_card(board_id, card_id)
        return self._replay(
            board_id, "card_events", "card_id", card_id, after=after, limit=limit
        )

    def _replay(
        self,
        board_id: str,
        table: str,
        column: str,
        scope_id: str,
        *,
        after: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        table = sql.identifier(table, _EVENT_TABLES)
        column = sql.identifier(column, _SCOPE_COLUMNS)
        with self.boards.reader(board_id) as conn:
            rows = conn.execute(
                text(
                    "SELECT seq, id,"  # noqa: S608 - from _EVENT_TABLES and _SCOPE_COLUMNS
                    f" {column} AS scope_id, type, payload_json, actor_id, actor_type, actor_name,"
                    f" created_at FROM {table}"
                    f" WHERE {column} = :id AND seq > :after ORDER BY seq LIMIT :limit"
                ),
                {"id": scope_id, "after": after, "limit": limit},
            ).mappings()
            events: list[dict[str, Any]] = []
            for row in rows:
                entry = dict(row)
                entry[column] = entry.pop("scope_id")
                events.append(serialize_event(entry))
            return events

    def shutdown(self) -> None:
        with self._lock:
            self._subscribers.clear()


def serialize_event(row: dict[str, Any]) -> dict[str, Any]:
    entry = dict(row)
    raw = entry.pop("payload_json", "{}")
    try:
        entry["payload"] = json.loads(raw)
    except (TypeError, ValueError):
        entry["payload"] = {}
    entry["seq"] = int(entry.get("seq") or 0)
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
