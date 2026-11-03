"""``ActivityRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import ACTIVITY_LOG_COLUMNS, ActivityLogRow
from ..activity import ActivityQuery

# What the feed formats into its SQL text (see core/sql.py); the names are ActivityQuery's keys.
_ACTIVITY_FILTERS: sql.Filters = (
    ("entity_type", "entity_type = :entity_type"),
    ("entity_id", "entity_id = :entity_id"),
    ("actor_type", "actor_type = :actor_type"),
    ("action", "action = :action"),
)

_SELECT_ACTIVITY = (
    f"SELECT {sql.column_list(ACTIVITY_LOG_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM activity_log"
)
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

    def count(self, query: ActivityQuery) -> int:
        where = sql.where(_ACTIVITY_FILTERS, query)
        statement = text(
            "SELECT COUNT(*) AS total FROM activity_log"  # noqa: S608 - from _ACTIVITY_FILTERS
            f"{where}"
        )
        row = self._connection.execute(statement, dict(query)).mappings().one()
        return values.integer(row, "total")

    def page(self, query: ActivityQuery, *, limit: int, offset: int) -> list[ActivityLogRow]:
        where = sql.where(_ACTIVITY_FILTERS, query)
        statement = text(
            f"{_SELECT_ACTIVITY}{where}"
            " ORDER BY timestamp DESC, id LIMIT :limit OFFSET :offset"
        )
        parameters = {**query, "limit": limit, "offset": offset}
        result = self._connection.execute(statement, parameters).mappings()
        return [ActivityLogRow.from_mapping(row) for row in result]
