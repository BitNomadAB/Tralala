"""A board's files: its database and its uploaded attachments, as ``BoardService`` creates,
copies, exports, imports, migrates and deletes them.

A board is a directory: ``board.sqlite`` plus ``attachments/``. The paths come from the board id
only, which the implementation validates, so no caller builds a path from user text. The storage
layer implements these Protocols (``BoardDatabaseManager`` and the Migration Manager); a unit test
uses a fake over a temporary directory.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

type ProblemReason = Literal[
    "not_a_database", "integrity_check_failed", "not_a_board_database", "unknown_schema_revision"
]


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseProblem:
    """Why a database file nobody here wrote cannot become a board."""

    reason: ProblemReason
    detail: str
    """What SQLite answered or what the check found, short and free of paths."""


class BoardFiles(Protocol):
    def create_database(self, board_id: str, description: str) -> None:
        """A new database at the schema head, holding only its metadata row."""
        ...

    def path(self, board_id: str) -> Path:
        """Where the board's database file is (or would be)."""
        ...

    def attachments_dir(self, board_id: str) -> Path:
        """Where the board's uploaded files are (or would be)."""
        ...

    def snapshot(self, board_id: str, target: Path) -> None:
        """A consistent copy of the board's database at ``target``, taken while it is in use."""
        ...

    def locked(self, board_id: str) -> AbstractContextManager[None]:
        """The board's exclusive lock, which readers, writers and restore share."""
        ...

    def delete_database(self, board_id: str) -> None:
        """Remove the board's directory; ``OSError`` when the host still holds a file in it."""
        ...


class MigrationOutcome(Protocol):
    @property
    def status(self) -> str:
        """``migrated``, ``up_to_date``, ``skipped`` or ``failed``."""
        ...


class BoardMigrator(Protocol):
    def check_imported(self, board_id: str) -> DatabaseProblem | None:
        """Judge the database file at the board's path before anything else opens it: ``None``
        when it is a sound board database the migrations can bring to the head, else why not.

        The file is read only, as a file of unknown origin: nothing in it runs, nothing is written
        next to it, and SQLite's integrity check is the first statement.
        """
        ...

    def migrate_board(self, board_id: str) -> MigrationOutcome:
        """Bring the board's database to the schema head, with a verified backup first."""
        ...
