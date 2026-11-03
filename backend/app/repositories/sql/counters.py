"""``CounterRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...db import values
from ..counters import BoardCounts

_COUNTS = text(
    "SELECT"
    " (SELECT COUNT(*) FROM loops WHERE archived_at IS NULL AND completed_at IS NULL) AS loops,"
    " (SELECT COUNT(*) FROM lists WHERE archived_at IS NULL) AS lists,"
    " (SELECT COUNT(*) FROM cards WHERE archived_at IS NULL) AS cards"
)


class SqlCounterRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def counts(self) -> BoardCounts:
        row = self._connection.execute(_COUNTS).mappings().one()
        return BoardCounts(
            loops=values.integer(row, "loops"),
            lists=values.integer(row, "lists"),
            cards=values.integer(row, "cards"),
        )
