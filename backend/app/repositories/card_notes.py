"""A person's notes on a Ticket, as ``CardNoteService`` and ``read_ticket`` use them."""

from __future__ import annotations

from typing import Final, Protocol, TypedDict

from ..db.generated.board import CARD_NOTES_COLUMNS, CardNotesRow

CARD_NOTE_EDITABLE: Final = ("text", "updated_at", "version")
"""The columns ``CardNoteRepository.update`` may set: the keys of ``CardNoteChanges``."""


class CardNoteChanges(TypedDict, total=False):
    """A note edit: only the columns present are written."""

    text: str
    updated_at: str
    version: int


class CardNoteRepository(Protocol):
    def get(self, note_id: str) -> CardNotesRow | None: ...

    def for_card(self, card_id: str) -> list[CardNotesRow]:
        """The card's notes, oldest first, in the order they were written within a second."""
        ...

    def add(self, row: CardNotesRow) -> None: ...

    def update(self, note_id: str, changes: CardNoteChanges) -> None:
        """Write ``changes`` (at least one column)."""
        ...

    def delete(self, note_id: str) -> None: ...


__all__ = ["CARD_NOTES_COLUMNS", "CARD_NOTE_EDITABLE", "CardNoteChanges", "CardNoteRepository"]
