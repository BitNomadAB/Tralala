"""``BoardMetadataRepository`` and ``LoopDefaultsRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...db import values
from ...db.generated.board import BoardLoopDefaultsRow

_CLAIM = text("UPDATE board_metadata SET id = :id, updated_at = :now WHERE rowid = 1")
_QUICK_CHECK = text("PRAGMA quick_check")
_ADD_LOOP_DEFAULTS = text(
    "INSERT INTO board_loop_defaults (id, column_names_json, updated_at)"
    " VALUES (:id, :column_names_json, :updated_at)"
)


class SqlBoardMetadataRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def claim(self, board_id: str, *, now: str) -> None:
        self._connection.execute(_CLAIM, {"id": board_id, "now": now})

    def quick_check(self) -> str:
        # One row when the database is sound; more than one is an error, as it always was.
        row = self._connection.execute(_QUICK_CHECK).mappings().one()
        return values.text(row, "quick_check")


class SqlLoopDefaultsRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def add(self, row: BoardLoopDefaultsRow) -> None:
        self._connection.execute(
            _ADD_LOOP_DEFAULTS,
            {
                "id": row.id,
                "column_names_json": row.column_names_json,
                "updated_at": row.updated_at,
            },
        )
