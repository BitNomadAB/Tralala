"""``CardNoteRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import CARD_NOTES_COLUMNS, CardNotesRow
from ..card_notes import CARD_NOTE_EDITABLE, CardNoteChanges

_NOTE = (
    f"SELECT {sql.column_list(CARD_NOTES_COLUMNS)}"  # noqa: S608 - from CARD_NOTES_COLUMNS
    " FROM card_notes"
)
_GET = text(f"{_NOTE} WHERE id = :id")
_FOR_CARD = text(f"{_NOTE} WHERE card_id = :id ORDER BY created_at, rowid")
_ADD = text(
    "INSERT INTO card_notes"
    " (id, card_id, author_actor_id, author_name, text, created_at, updated_at, version)"
    " VALUES (:id, :card_id, :author_actor_id, :author_name, :text, :created_at, :updated_at,"
    " :version)"
)
_DELETE = text("DELETE FROM card_notes WHERE id = :id")


class SqlCardNoteRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, note_id: str) -> CardNotesRow | None:
        row = self._connection.execute(_GET, {"id": note_id}).mappings().first()
        return None if row is None else CardNotesRow.from_mapping(row)

    def for_card(self, card_id: str) -> list[CardNotesRow]:
        result = self._connection.execute(_FOR_CARD, {"id": card_id}).mappings()
        return [CardNotesRow.from_mapping(row) for row in result]

    def add(self, row: CardNotesRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "card_id": row.card_id,
                "author_actor_id": row.author_actor_id,
                "author_name": row.author_name,
                "text": row.text,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "version": row.version,
            },
        )

    def update(self, note_id: str, changes: CardNoteChanges) -> None:
        columns = sql.assignments(changes, CARD_NOTE_EDITABLE)
        statement = text(f"UPDATE card_notes SET {columns} WHERE id = :id")  # noqa: S608 - from CARD_NOTE_EDITABLE
        self._connection.execute(statement, {**changes, "id": note_id})

    def delete(self, note_id: str) -> None:
        self._connection.execute(_DELETE, {"id": note_id})
