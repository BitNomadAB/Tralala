"""``LabelRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import LABELS_COLUMNS, LabelsRow
from ..labels import LABEL_EDITABLE, LabelChanges

_COLUMNS = sql.column_list(LABELS_COLUMNS)
_ALL = text(f"SELECT {_COLUMNS} FROM labels ORDER BY name")  # noqa: S608 - from LABELS_COLUMNS
_GET = text(f"SELECT {_COLUMNS} FROM labels WHERE id = :id")  # noqa: S608 - from LABELS_COLUMNS
_FIND = text(
    f"SELECT {_COLUMNS} FROM labels"  # noqa: S608 - from LABELS_COLUMNS
    " WHERE id = :ref OR name = :ref"
)
_BY_NAME = text(
    f"SELECT {_COLUMNS} FROM labels WHERE name = :name"  # noqa: S608 - from LABELS_COLUMNS
)
_ADD = text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)")
_DELETE = text("DELETE FROM labels WHERE id = :id")


class SqlLabelRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def all(self) -> list[LabelsRow]:
        result = self._connection.execute(_ALL).mappings()
        return [LabelsRow.from_mapping(row) for row in result]

    def get(self, label_id: str) -> LabelsRow | None:
        row = self._connection.execute(_GET, {"id": label_id}).mappings().first()
        return None if row is None else LabelsRow.from_mapping(row)

    def find(self, reference: str) -> LabelsRow | None:
        row = self._connection.execute(_FIND, {"ref": reference}).mappings().first()
        return None if row is None else LabelsRow.from_mapping(row)

    def by_name(self, name: str) -> LabelsRow | None:
        row = self._connection.execute(_BY_NAME, {"name": name}).mappings().first()
        return None if row is None else LabelsRow.from_mapping(row)

    def add(self, row: LabelsRow) -> None:
        self._connection.execute(_ADD, {"id": row.id, "name": row.name, "color": row.color})

    def update(self, label_id: str, changes: LabelChanges) -> None:
        columns = sql.assignments(changes, LABEL_EDITABLE)
        statement = text(f"UPDATE labels SET {columns} WHERE id = :id")  # noqa: S608 - from LABEL_EDITABLE
        self._connection.execute(statement, {**changes, "id": label_id})

    def delete(self, label_id: str) -> None:
        self._connection.execute(_DELETE, {"id": label_id})
