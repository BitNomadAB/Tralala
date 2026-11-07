"""``CardNoteRepository`` over a list kept in insertion order, which is SQLite's rowid order."""

from __future__ import annotations

from collections.abc import Container

from app.db.generated.board import CardNotesRow
from app.repositories.card_notes import CardNoteChanges
from tests.unit.fakes.registry import ConstraintError


class FakeCardNoteRepository:
    def __init__(self, notes: list[CardNotesRow], cards: Container[str]) -> None:
        self._notes = notes
        # The board's cards, live: a note names a card that exists (the foreign key).
        self._cards = cards

    def _index(self, note_id: str) -> int | None:
        return next((i for i, note in enumerate(self._notes) if note.id == note_id), None)

    def get(self, note_id: str) -> CardNotesRow | None:
        index = self._index(note_id)
        return None if index is None else self._notes[index]

    def for_card(self, card_id: str) -> list[CardNotesRow]:
        # ORDER BY created_at, rowid: a stable sort over the insertion order.
        return sorted(
            (note for note in self._notes if note.card_id == card_id),
            key=lambda note: note.created_at,
        )

    def add(self, row: CardNotesRow) -> None:
        if self._index(row.id) is not None:
            raise ConstraintError(f"card_notes.id {row.id} exists")
        if row.card_id not in self._cards:
            raise ConstraintError(f"card_notes.card_id {row.card_id} does not exist")
        if not 1 <= len(row.text) <= 4000:
            raise ConstraintError("card_notes.text is 1 to 4000 characters")
        self._notes.append(row)

    def update(self, note_id: str, changes: CardNoteChanges) -> None:
        if not changes:
            raise ValueError("an update names at least one column")
        index = self._index(note_id)
        if index is None:
            return
        note = self._notes[index]
        self._notes[index] = note.__replace__(
            text=changes.get("text", note.text),
            updated_at=changes.get("updated_at", note.updated_at),
            version=changes.get("version", note.version),
        )

    def delete(self, note_id: str) -> None:
        index = self._index(note_id)
        if index is not None:
            del self._notes[index]
