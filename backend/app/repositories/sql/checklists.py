"""``ChecklistRepository`` and ``ChecklistItemRepository`` over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import (
    CHECKLIST_ITEMS_COLUMNS,
    CHECKLISTS_COLUMNS,
    ChecklistItemsRow,
    ChecklistsRow,
)
from ..checklists import CHECKLIST_ITEM_EDITABLE, ChecklistItemChanges

# --- checklists ----------------------------------------------------------------------------------

_CHECKLIST = (
    f"SELECT {sql.column_list(CHECKLISTS_COLUMNS)}"  # noqa: S608 - from CHECKLISTS_COLUMNS
    " FROM checklists"
)
_GET_CHECKLIST = text(f"{_CHECKLIST} WHERE id = :id")
_CHECKLISTS_FOR_CARD = text(f"{_CHECKLIST} WHERE card_id = :id ORDER BY position, id")
_RENUMBER_CHECKLIST = text("UPDATE checklists SET position = :position WHERE id = :id")
_ADD_CHECKLIST = text(
    "INSERT INTO checklists (id, card_id, title, position)"
    " VALUES (:id, :card_id, :title, :position)"
)
_RENAME_CHECKLIST = text("UPDATE checklists SET title = :title WHERE id = :id")
_DELETE_CHECKLIST = text("DELETE FROM checklists WHERE id = :id")

# --- items ---------------------------------------------------------------------------------------

_ITEM = (
    f"SELECT {sql.column_list(CHECKLIST_ITEMS_COLUMNS)}"  # noqa: S608 - from CHECKLIST_ITEMS_COLUMNS
    " FROM checklist_items"
)
_GET_ITEM = text(f"{_ITEM} WHERE id = :id")
_ITEMS_FOR_CARD = text(
    f"SELECT {sql.column_list(CHECKLIST_ITEMS_COLUMNS, 'i')}"  # noqa: S608 - from CHECKLIST_ITEMS_COLUMNS
    " FROM checklist_items i JOIN checklists ch ON ch.id = i.checklist_id"
    " WHERE ch.card_id = :id ORDER BY i.position, i.id"
)
_ITEMS_FOR_CHECKLIST = text(f"{_ITEM} WHERE checklist_id = :id ORDER BY position, id")
_RENUMBER_ITEM = text("UPDATE checklist_items SET position = :position WHERE id = :id")
_ADD_ITEM = text(
    "INSERT INTO checklist_items (id, checklist_id, text, completed, position)"
    " VALUES (:id, :checklist_id, :text, :completed, :position)"
)
_DELETE_ITEM = text("DELETE FROM checklist_items WHERE id = :id")


class SqlChecklistRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, checklist_id: str) -> ChecklistsRow | None:
        row = self._connection.execute(_GET_CHECKLIST, {"id": checklist_id}).mappings().first()
        return None if row is None else ChecklistsRow.from_mapping(row)

    def for_card(self, card_id: str) -> list[ChecklistsRow]:
        result = self._connection.execute(_CHECKLISTS_FOR_CARD, {"id": card_id}).mappings()
        return [ChecklistsRow.from_mapping(row) for row in result]

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for checklist_id, position in positions:
            self._connection.execute(
                _RENUMBER_CHECKLIST, {"position": position, "id": checklist_id}
            )

    def add(self, row: ChecklistsRow) -> None:
        self._connection.execute(
            _ADD_CHECKLIST,
            {"id": row.id, "card_id": row.card_id, "title": row.title, "position": row.position},
        )

    def rename(self, checklist_id: str, title: str) -> None:
        self._connection.execute(_RENAME_CHECKLIST, {"title": title, "id": checklist_id})

    def delete(self, checklist_id: str) -> None:
        self._connection.execute(_DELETE_CHECKLIST, {"id": checklist_id})


class SqlChecklistItemRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, item_id: str) -> ChecklistItemsRow | None:
        row = self._connection.execute(_GET_ITEM, {"id": item_id}).mappings().first()
        return None if row is None else ChecklistItemsRow.from_mapping(row)

    def for_card(self, card_id: str) -> list[ChecklistItemsRow]:
        result = self._connection.execute(_ITEMS_FOR_CARD, {"id": card_id}).mappings()
        return [ChecklistItemsRow.from_mapping(row) for row in result]

    def for_checklist(self, checklist_id: str) -> list[ChecklistItemsRow]:
        result = self._connection.execute(_ITEMS_FOR_CHECKLIST, {"id": checklist_id}).mappings()
        return [ChecklistItemsRow.from_mapping(row) for row in result]

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        for item_id, position in positions:
            self._connection.execute(_RENUMBER_ITEM, {"position": position, "id": item_id})

    def add(self, row: ChecklistItemsRow) -> None:
        self._connection.execute(
            _ADD_ITEM,
            {
                "id": row.id,
                "checklist_id": row.checklist_id,
                "text": row.text,
                "completed": row.completed,
                "position": row.position,
            },
        )

    def update(self, item_id: str, changes: ChecklistItemChanges) -> None:
        columns = sql.assignments(changes, CHECKLIST_ITEM_EDITABLE)
        statement = text(f"UPDATE checklist_items SET {columns} WHERE id = :id")  # noqa: S608 - from CHECKLIST_ITEM_EDITABLE
        self._connection.execute(statement, {**changes, "id": item_id})

    def delete(self, item_id: str) -> None:
        self._connection.execute(_DELETE_ITEM, {"id": item_id})
