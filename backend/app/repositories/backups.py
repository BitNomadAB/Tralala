"""A board's snapshots at the database level, as ``BackupService`` checks and restores them.

The files themselves (where the database is, the lock, taking a consistent copy) are
``BoardFiles``; this Protocol is the part that has to read a database: judging a snapshot before it
may replace a board, putting it in place, and reporting a board's health afterwards. The storage
layer implements it; a unit test uses a fake over the same temporary directory as the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypedDict

from ..core.integrity import SnapshotProblem


class FileVerification(TypedDict):
    """What SQLite's integrity check says about one snapshot file."""

    integrity: str
    ok: bool


class BoardHealth(TypedDict):
    """A board's database after a restore: integrity, broken references, schema, row counts."""

    integrity: str
    foreign_key_violations: list[dict[str, object]]
    schema_version: int
    schema_revision: str | None
    counts: dict[str, int]


class BoardSnapshots(Protocol):
    def exists(self, board_id: str) -> bool:
        """Whether the board's database file exists."""
        ...

    def close(self, board_id: str) -> None:
        """Let go of the board's open handles, so its file can be replaced."""
        ...

    def check_snapshot(self, source: Path) -> SnapshotProblem | None:
        """``None`` when the snapshot may replace a board's database, else why not."""
        ...

    def restore_snapshot(self, source: Path, board_id: str) -> None:
        """Copy an accepted snapshot over the board's database in one transaction."""
        ...

    def verify_file(self, path: Path) -> FileVerification: ...

    def health(self, board_id: str) -> BoardHealth: ...
