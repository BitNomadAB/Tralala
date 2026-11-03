"""``LabelRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import LABELS_COLUMNS, LabelsRow

_ALL = text(
    f"SELECT {sql.column_list(LABELS_COLUMNS)}"  # noqa: S608 - from LABELS_COLUMNS
    " FROM labels ORDER BY name"
)
_FIND = text(
    f"SELECT {sql.column_list(LABELS_COLUMNS)}"  # noqa: S608 - from LABELS_COLUMNS
    " FROM labels WHERE id = :ref OR name = :ref"
)
_ADD = text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)")


class SqlLabelRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def all(self) -> list[LabelsRow]:
        result = self._connection.execute(_ALL).mappings()
        return [LabelsRow.from_mapping(row) for row in result]

    def find(self, reference: str) -> LabelsRow | None:
        row = self._connection.execute(_FIND, {"ref": reference}).mappings().first()
        return None if row is None else LabelsRow.from_mapping(row)

    def add(self, row: LabelsRow) -> None:
        self._connection.execute(_ADD, {"id": row.id, "name": row.name, "color": row.color})
