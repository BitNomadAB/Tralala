"""Ticket search inside one Loop: SQLite's FTS5 index when the board has it, ``LIKE`` otherwise.

FTS5 is an accelerator, not part of the schema: a runtime without it creates no index, and the
search falls back to ``LIKE``. Whether a board has the index is a property of its database file, so
it is asked of ``FullTextIndex`` (``BoardDatabaseManager``), not of a reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db.generated.board import CardsRow


class FullTextIndex(Protocol):
    def fts_available(self, board_id: str) -> bool:
        """Whether the board's database has the FTS5 card index; the first question creates the
        index when SQLite supports FTS5."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CardSearch:
    """The cards of one Loop a search asks for; every field that is set narrows the result."""

    loop_id: str
    match: str | None = None
    """An FTS5 ``MATCH`` expression over the title and the description; needs the index."""
    contains: str | None = None
    """Text in the title or the description (SQL ``LIKE``, so ``%`` and ``_`` are wildcards)."""
    include_archived: bool = False
    priority: str | None = None
    label: str | None = None
    """A label's id or name."""
    completed: bool | None = None
    overdue_at: str | None = None
    """Open cards due before this moment."""
    list_id: str | None = None


class CardSearchRepository(Protocol):
    def count(self, search: CardSearch) -> int: ...

    def page(self, search: CardSearch, *, limit: int, offset: int) -> list[CardsRow]:
        """``limit`` cards from ``offset``, the most recently updated first, then by id."""
        ...
