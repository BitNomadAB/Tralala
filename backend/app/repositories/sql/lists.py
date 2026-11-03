"""``ListRepository`` over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import LISTS_COLUMNS, ListsRow

_COLUMNS = sql.column_list(LISTS_COLUMNS)
_GET = text(f"SELECT {_COLUMNS} FROM lists WHERE id = :id")  # noqa: S608 - from LISTS_COLUMNS
_FOR_LOOP = text(
    f"SELECT {_COLUMNS} FROM lists"  # noqa: S608 - from LISTS_COLUMNS
    " WHERE loop_id = :loop_id ORDER BY position, id"
)
_ACTIVE_FOR_LOOP = text(
    f"SELECT {_COLUMNS} FROM lists"  # noqa: S608 - from LISTS_COLUMNS
    " WHERE loop_id = :loop_id AND archived_at IS NULL ORDER BY position, id"
)
_POSITIONS = text(
    "SELECT id, position FROM lists WHERE loop_id = :loop_id AND archived_at IS NULL"
    " ORDER BY position, id"
)
_POSITIONS_EXCEPT = text(
    "SELECT id, position FROM lists WHERE loop_id = :loop_id AND archived_at IS NULL"
    " AND id != :id ORDER BY position, id"
)
_INSERT = text(
    "INSERT INTO lists (id, loop_id, name, position, created_at, updated_at, archived_at)"
    " VALUES (:id, :loop_id, :name, :position, :created_at, :updated_at, :archived_at)"
)
_RENAME = text("UPDATE lists SET name = :name, updated_at = :now WHERE id = :id")
_MOVE = text("UPDATE lists SET position = :position, updated_at = :now WHERE id = :id")
_RENUMBER = text("UPDATE lists SET position = :position WHERE id = :id")
_ARCHIVE = text("UPDATE lists SET archived_at = :now, updated_at = :now WHERE id = :id")
_RESTORE = text(
    "UPDATE lists SET archived_at = NULL, position = :position, updated_at = :now WHERE id = :id"
)
_DELETE = text("DELETE FROM lists WHERE id = :id")
_ACTIVE_CARD_COUNTS = text(
    "SELECT list_id, COUNT(*) AS total FROM cards"
    " WHERE loop_id = :loop_id AND archived_at IS NULL GROUP BY list_id"
)
_ACTIVE_CARD_COUNT = text(
    "SELECT COUNT(*) AS total FROM cards WHERE list_id = :id AND archived_at IS NULL"
)
_PLANNED_CARD_COUNT = text(
    "SELECT COUNT(*) AS total FROM cards WHERE list_id = :id AND plan_item_id IS NOT NULL"
)


class SqlListRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, list_id: str) -> ListsRow | None:
        row = self._connection.execute(_GET, {"id": list_id}).mappings().first()
        return None if row is None else ListsRow.from_mapping(row)

    def for_loop(self, loop_id: str, *, include_archived: bool) -> list[ListsRow]:
        statement = _FOR_LOOP if include_archived else _ACTIVE_FOR_LOOP
        result = self._connection.execute(statement, {"loop_id": loop_id}).mappings()
        return [ListsRow.from_mapping(row) for row in result]

    def positions(self, loop_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        if exclude is None:
            result = self._connection.execute(_POSITIONS, {"loop_id": loop_id})
        else:
            parameters = {"loop_id": loop_id, "id": exclude}
            result = self._connection.execute(_POSITIONS_EXCEPT, parameters)
        return [
            (values.text(row, "id"), values.integer(row, "position")) for row in result.mappings()
        ]

    def add(self, row: ListsRow) -> None:
        self._connection.execute(
            _INSERT,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "name": row.name,
                "position": row.position,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "archived_at": row.archived_at,
            },
        )

    def rename(self, list_id: str, name: str, *, now: str) -> None:
        self._connection.execute(_RENAME, {"name": name, "now": now, "id": list_id})

    def move(self, list_id: str, position: int, *, now: str) -> None:
        self._connection.execute(_MOVE, {"position": position, "now": now, "id": list_id})

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for list_id, position in positions:
            self._connection.execute(_RENUMBER, {"position": position, "id": list_id})

    def archive(self, list_id: str, *, now: str) -> None:
        self._connection.execute(_ARCHIVE, {"now": now, "id": list_id})

    def restore(self, list_id: str, position: int, *, now: str) -> None:
        self._connection.execute(_RESTORE, {"position": position, "now": now, "id": list_id})

    def delete(self, list_id: str) -> None:
        self._connection.execute(_DELETE, {"id": list_id})

    def active_card_counts(self, loop_id: str) -> dict[str, int]:
        result = self._connection.execute(_ACTIVE_CARD_COUNTS, {"loop_id": loop_id}).mappings()
        return {values.text(row, "list_id"): values.integer(row, "total") for row in result}

    def active_card_count(self, list_id: str) -> int:
        row = self._connection.execute(_ACTIVE_CARD_COUNT, {"id": list_id}).mappings().one()
        return values.integer(row, "total")

    def planned_card_count(self, list_id: str) -> int:
        row = self._connection.execute(_PLANNED_CARD_COUNT, {"id": list_id}).mappings().one()
        return values.integer(row, "total")
