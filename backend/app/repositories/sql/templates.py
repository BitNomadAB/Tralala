"""``BoardTemplateRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...core import sql
from ...db.generated.registry import BOARD_TEMPLATES_COLUMNS, BoardTemplatesRow
from ..errors import ConstraintViolationError

_TEMPLATE = (
    f"SELECT {sql.column_list(BOARD_TEMPLATES_COLUMNS)}"  # noqa: S608 - from generated columns
    " FROM board_templates"
)
_ALL = text(f"{_TEMPLATE} ORDER BY name")
_GET = text(f"{_TEMPLATE} WHERE id = :id")
_ADD = text(
    "INSERT INTO board_templates"
    " (id, name, description, lists_json, labels_json, created_at, updated_at)"
    " VALUES (:id, :name, :description, :lists_json, :labels_json, :created_at, :updated_at)"
)
_UPDATE = text(
    "UPDATE board_templates SET name = :name, description = :description,"
    " lists_json = :lists_json, labels_json = :labels_json, updated_at = :updated_at"
    " WHERE id = :id"
)
_DELETE = text("DELETE FROM board_templates WHERE id = :id")


def _parameters(row: BoardTemplatesRow) -> dict[str, str]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "lists_json": row.lists_json,
        "labels_json": row.labels_json,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class SqlBoardTemplateRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def all(self) -> list[BoardTemplatesRow]:
        result = self._connection.execute(_ALL).mappings()
        return [BoardTemplatesRow.from_mapping(row) for row in result]

    def get(self, template_id: str) -> BoardTemplatesRow | None:
        row = self._connection.execute(_GET, {"id": template_id}).mappings().first()
        return None if row is None else BoardTemplatesRow.from_mapping(row)

    def add(self, row: BoardTemplatesRow) -> None:
        try:
            self._connection.execute(_ADD, _parameters(row))
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def update(self, row: BoardTemplatesRow) -> None:
        try:
            self._connection.execute(_UPDATE, _parameters(row))
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def delete(self, template_id: str) -> None:
        self._connection.execute(_DELETE, {"id": template_id})
