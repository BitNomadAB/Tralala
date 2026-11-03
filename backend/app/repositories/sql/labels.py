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


class SqlLabelRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def all(self) -> list[LabelsRow]:
        result = self._connection.execute(_ALL).mappings()
        return [LabelsRow.from_mapping(row) for row in result]
