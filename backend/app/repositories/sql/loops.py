"""``LoopRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import LOOPS_COLUMNS, LoopsRow

_COLUMNS = sql.column_list(LOOPS_COLUMNS)
_GET = text(f"SELECT {_COLUMNS} FROM loops WHERE id = :id")  # noqa: S608 - from LOOPS_COLUMNS


class SqlLoopRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, loop_id: str) -> LoopsRow | None:
        row = self._connection.execute(_GET, {"id": loop_id}).mappings().first()
        return None if row is None else LoopsRow.from_mapping(row)
