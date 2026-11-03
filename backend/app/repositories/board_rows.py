"""The registry's row for each board and its cached dashboard counters.

A board's data lives in its own database; the registry holds what is known before that database is
opened (name, status, schema state) and the counters measured from it, so a dashboard does not open
every board file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypedDict

from ..db.generated.registry import BoardsRow, BoardStatsRow

# The columns a board list may be sorted by, as the page formats them into its SQL text.
BOARD_SORTS = ("name", "status", "created_at", "updated_at")

# The columns of ``BoardChanges``, as the update formats them into its SQL text (core/sql.py).
BOARD_EDITABLE = (
    "name",
    "description",
    "status",
    "archived_at",
    "schema_version",
    "schema_revision",
)


class BoardChanges(TypedDict, total=False):
    """The columns of a board row that change after it is created; ``updated_at`` always does."""

    name: str
    description: str
    status: str
    archived_at: str | None
    schema_version: int
    schema_revision: str | None


class BoardRowRepository(Protocol):
    def get(self, board_id: str) -> BoardsRow | None: ...

    def count(self, *, status: str | None, contains: str | None) -> int:
        """Boards with that status (any when None) whose name or description contains the text
        (SQLite ``LIKE``: ASCII letters ignore case, ``%`` and ``_`` are wildcards)."""
        ...

    def page(
        self,
        *,
        status: str | None,
        contains: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> list[BoardsRow]:
        """The boards ``count`` counts, ordered by ``sort`` (one of ``BOARD_SORTS``) and then by
        name, ``limit`` of them from ``offset``."""
        ...

    def all(self) -> list[BoardsRow]:
        """Every board, in the table's own order."""
        ...

    def with_status(self, status: str) -> list[BoardsRow]:
        """Every board in that status, in the table's own order."""
        ...

    def most_recent(self, *, status: str, limit: int) -> list[BoardsRow]:
        """At most ``limit`` boards in that status, the most recently updated first (boards
        updated at the same moment in SQLite's own order)."""
        ...

    def add(self, row: BoardsRow) -> None: ...

    def update(self, board_id: str, changes: BoardChanges, *, now: str) -> None:
        """Write ``changes`` (at least one) and set ``updated_at`` to ``now``."""
        ...

    def delete(self, board_id: str) -> None:
        """Delete the row; its counters and its agent and repository links go with it."""
        ...


class BoardStatsRepository(Protocol):
    def for_boards(self, board_ids: Sequence[str]) -> dict[str, BoardStatsRow]:
        """The stored counters of those boards that have them, by board id."""
        ...

    def store(self, row: BoardStatsRow) -> None:
        """Insert the board's counters, or replace the ones stored."""
        ...

    def forget(self, board_id: str) -> None: ...
