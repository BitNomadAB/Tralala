"""``EventRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import (
    CARD_EVENTS_COLUMNS,
    DISCUSSION_EVENTS_COLUMNS,
    CardEventsRow,
    DiscussionEventsRow,
)
from ..events import NewEvent

_EVENT_VALUES = (
    " VALUES (:id, :scope_id, :type, :payload_json, :actor_id, :actor_type, :actor_name,"
    " :created_at)"
)
_ADD_DISCUSSION = text(
    "INSERT INTO discussion_events (id, discussion_id, type, payload_json, actor_id, actor_type,"
    " actor_name, created_at)" + _EVENT_VALUES
)
_ADD_CARD = text(
    "INSERT INTO card_events (id, card_id, type, payload_json, actor_id, actor_type, actor_name,"
    " created_at)" + _EVENT_VALUES
)
_THREAD_COLUMNS = sql.column_list(DISCUSSION_EVENTS_COLUMNS)
_TICKET_COLUMNS = sql.column_list(CARD_EVENTS_COLUMNS)
_DISCUSSION_EVENTS = text(
    f"SELECT {_THREAD_COLUMNS} FROM discussion_events"  # noqa: S608 - from DISCUSSION_EVENTS_COLUMNS
    " WHERE discussion_id = :id AND seq > :after ORDER BY seq LIMIT :limit"
)
_CARD_EVENTS = text(
    f"SELECT {_TICKET_COLUMNS} FROM card_events"  # noqa: S608 - from CARD_EVENTS_COLUMNS
    " WHERE card_id = :id AND seq > :after ORDER BY seq LIMIT :limit"
)
_DISCUSSION_EXISTS = text("SELECT 1 FROM discussion_threads WHERE id = :id")


class SqlEventRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add_discussion_event(self, discussion_id: str, event: NewEvent) -> int:
        result = self._connection.execute(_ADD_DISCUSSION, {"scope_id": discussion_id, **event})
        return int(result.lastrowid or 0)

    def add_card_event(self, card_id: str, event: NewEvent) -> int:
        result = self._connection.execute(_ADD_CARD, {"scope_id": card_id, **event})
        return int(result.lastrowid or 0)

    def discussion_events(
        self, discussion_id: str, *, after: int, limit: int
    ) -> list[DiscussionEventsRow]:
        result = self._connection.execute(
            _DISCUSSION_EVENTS, {"id": discussion_id, "after": after, "limit": limit}
        ).mappings()
        return [DiscussionEventsRow.from_mapping(row) for row in result]

    def card_events(self, card_id: str, *, after: int, limit: int) -> list[CardEventsRow]:
        result = self._connection.execute(
            _CARD_EVENTS, {"id": card_id, "after": after, "limit": limit}
        ).mappings()
        return [CardEventsRow.from_mapping(row) for row in result]

    def discussion_exists(self, discussion_id: str) -> bool:
        found = self._connection.execute(_DISCUSSION_EXISTS, {"id": discussion_id}).first()
        return found is not None
