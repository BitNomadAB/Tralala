"""``LoopNoteRepository`` over a list kept in insertion order, which is SQLite's rowid order."""

from __future__ import annotations

from app.db.generated.board import LoopNotesRow
from tests.unit.fakes.registry import ConstraintError


class FakeLoopNoteRepository:
    def __init__(self, notes: list[LoopNotesRow]) -> None:
        self._notes = notes

    def _ordered(self, loop_id: str) -> list[LoopNotesRow]:
        # ORDER BY created_at, rowid: a stable sort over the insertion order.
        return sorted(
            (note for note in self._notes if note.loop_id == loop_id),
            key=lambda note: note.created_at,
        )

    def add(self, row: LoopNotesRow) -> None:
        if any(note.id == row.id for note in self._notes):
            raise ConstraintError(f"loop_notes.id {row.id} exists")
        self._notes.append(row)

    def page(self, loop_id: str, *, limit: int, before: str | None) -> list[LoopNotesRow]:
        notes = self._ordered(loop_id)
        if before is not None:
            cut = next((index for index, note in enumerate(notes) if note.id == before), 0)
            notes = notes[:cut]
        return notes[-limit:] if limit > 0 else []

    def for_loop(self, loop_id: str) -> list[LoopNotesRow]:
        return self._ordered(loop_id)

    def count(self, loop_id: str) -> int:
        return len(self._ordered(loop_id))

    def latest_by(self, loop_id: str, actor_id: str, content_sha256: str) -> LoopNotesRow | None:
        found = [
            note
            for note in self._ordered(loop_id)
            if note.author_actor_id == actor_id and note.content_sha256 == content_sha256
        ]
        return found[-1] if found else None
