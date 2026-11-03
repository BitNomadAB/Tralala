"""``BoardMetadataRepository`` and ``LoopDefaultsRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import BOARD_LOOP_DEFAULTS_COLUMNS, BoardLoopDefaultsRow

_CLAIM = text("UPDATE board_metadata SET id = :id, updated_at = :now WHERE rowid = 1")
_LOOP_DEFAULTS = text(
    f"SELECT {sql.column_list(BOARD_LOOP_DEFAULTS_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM board_loop_defaults WHERE id = 1"
)
_ADD_LOOP_DEFAULTS = text(
    "INSERT INTO board_loop_defaults (id, column_names_json, updated_at)"
    " VALUES (:id, :column_names_json, :updated_at)"
)


class SqlBoardMetadataRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def claim(self, board_id: str, *, now: str) -> None:
        self._connection.execute(_CLAIM, {"id": board_id, "now": now})


class SqlLoopDefaultsRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self) -> BoardLoopDefaultsRow | None:
        row = self._connection.execute(_LOOP_DEFAULTS).mappings().first()
        return None if row is None else BoardLoopDefaultsRow.from_mapping(row)

    def add(self, row: BoardLoopDefaultsRow) -> None:
        self._connection.execute(
            _ADD_LOOP_DEFAULTS,
            {
                "id": row.id,
                "column_names_json": row.column_names_json,
                "updated_at": row.updated_at,
            },
        )
