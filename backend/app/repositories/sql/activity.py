"""``ActivityRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...db.generated.board import ActivityLogRow

_INSERT = text(
    "INSERT INTO activity_log"
    " (id, actor_id, actor_type, action, entity_type, entity_id, request_id, timestamp,"
    "  changes_json)"
    " VALUES (:id, :actor_id, :actor_type, :action, :entity_type, :entity_id, :request_id,"
    "         :timestamp, :changes_json)"
)


class SqlActivityRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, entry: ActivityLogRow) -> None:
        self._connection.execute(
            _INSERT,
            {
                "id": entry.id,
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "request_id": entry.request_id,
                "timestamp": entry.timestamp,
                "changes_json": entry.changes_json,
            },
        )
