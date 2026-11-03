"""``BoardRowRepository`` and ``BoardStatsRepository`` over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.registry import BOARD_STATS_COLUMNS, BOARDS_COLUMNS, BoardsRow, BoardStatsRow
from ..board_rows import BOARD_EDITABLE, BoardChanges

_BOARD = text(
    f"SELECT {sql.column_list(BOARDS_COLUMNS)}"  # noqa: S608 - from BOARDS_COLUMNS
    " FROM boards WHERE id = :id"
)
_ADD_BOARD = text(
    "INSERT INTO boards"
    " (id, name, description, status, created_at, updated_at, archived_at, schema_version,"
    "  schema_revision)"
    " VALUES (:id, :name, :description, :status, :created_at, :updated_at, :archived_at,"
    "         :schema_version, :schema_revision)"
)
_DELETE_BOARD = text("DELETE FROM boards WHERE id = :id")

_STATS = text(
    f"SELECT {sql.column_list(BOARD_STATS_COLUMNS)}"  # noqa: S608 - from BOARD_STATS_COLUMNS
    " FROM board_stats WHERE board_id IN :board_ids"
).bindparams(bindparam("board_ids", expanding=True))
_STORE_STATS = text(
    "INSERT INTO board_stats (board_id, loop_count, list_count, card_count, measured_at)"
    " VALUES (:board_id, :loop_count, :list_count, :card_count, :measured_at)"
    " ON CONFLICT(board_id) DO UPDATE SET"
    "  loop_count = excluded.loop_count,"
    "  list_count = excluded.list_count,"
    "  card_count = excluded.card_count,"
    "  measured_at = excluded.measured_at"
)
_FORGET_STATS = text("DELETE FROM board_stats WHERE board_id = :board_id")


class SqlBoardRowRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, board_id: str) -> BoardsRow | None:
        row = self._connection.execute(_BOARD, {"id": board_id}).mappings().first()
        return None if row is None else BoardsRow.from_mapping(row)

    def add(self, row: BoardsRow) -> None:
        self._connection.execute(
            _ADD_BOARD,
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "archived_at": row.archived_at,
                "schema_version": row.schema_version,
                "schema_revision": row.schema_revision,
            },
        )

    def update(self, board_id: str, changes: BoardChanges, *, now: str) -> None:
        assignments = sql.assignments(changes, BOARD_EDITABLE)
        statement = text(
            "UPDATE boards"  # noqa: S608 - from BOARD_EDITABLE
            f" SET {assignments}, updated_at = :updated_at WHERE id = :board_id"
        )
        self._connection.execute(statement, {**changes, "updated_at": now, "board_id": board_id})

    def delete(self, board_id: str) -> None:
        self._connection.execute(_DELETE_BOARD, {"id": board_id})


class SqlBoardStatsRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_boards(self, board_ids: Sequence[str]) -> dict[str, BoardStatsRow]:
        if not board_ids:
            return {}
        result = self._connection.execute(_STATS, {"board_ids": list(board_ids)}).mappings()
        rows = [BoardStatsRow.from_mapping(row) for row in result]
        return {row.board_id: row for row in rows}

    def store(self, row: BoardStatsRow) -> None:
        self._connection.execute(
            _STORE_STATS,
            {
                "board_id": row.board_id,
                "loop_count": row.loop_count,
                "list_count": row.list_count,
                "card_count": row.card_count,
                "measured_at": row.measured_at,
            },
        )

    def forget(self, board_id: str) -> None:
        self._connection.execute(_FORGET_STATS, {"board_id": board_id})
