"""``BoardSnapshots`` on ``BoardDatabaseManager`` and SQLite's backup API."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from ...core.integrity import SnapshotProblem
from ...storage import sqlite as storage_sqlite
from ...storage.board_db import BoardDatabaseManager
from ...storage.schema import runner
from ..backups import BoardHealth, FileVerification

# The tables a health report counts.
_COUNTS = text(
    "SELECT (SELECT COUNT(*) FROM lists) AS lists, (SELECT COUNT(*) FROM cards) AS cards,"
    " (SELECT COUNT(*) FROM labels) AS labels, (SELECT COUNT(*) FROM checklists) AS checklists,"
    " (SELECT COUNT(*) FROM comments) AS comments,"
    " (SELECT COUNT(*) FROM activity_log) AS activity_log"
)
_COUNTED_TABLES = ("lists", "cards", "labels", "checklists", "comments", "activity_log")


class SqliteBoardSnapshots:
    def __init__(self, boards: BoardDatabaseManager) -> None:
        self._boards = boards

    def exists(self, board_id: str) -> bool:
        return self._boards.exists(board_id)

    def close(self, board_id: str) -> None:
        self._boards.close(board_id)

    def check_snapshot(self, source: Path) -> SnapshotProblem | None:
        return storage_sqlite.check_snapshot(source)

    def restore_snapshot(self, source: Path, board_id: str) -> None:
        storage_sqlite.restore_snapshot(source, self._boards.path(board_id))

    def verify_file(self, path: Path) -> FileVerification:
        try:
            connection = storage_sqlite.connect_sqlite(path)
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return {"integrity": f"unreadable: {exc}", "ok": False}
        integrity = str(row[0]) if row is not None else "unreadable: no answer"
        return {"integrity": integrity, "ok": integrity == "ok"}

    def health(self, board_id: str) -> BoardHealth:
        with self._boards.reader(board_id) as conn:
            integrity = str(conn.exec_driver_sql("PRAGMA integrity_check").scalar_one())
            foreign_keys: list[dict[str, object]] = [
                {str(key): value for key, value in row.items()}
                for row in conn.exec_driver_sql("PRAGMA foreign_key_check").mappings().all()
            ]
            revision = runner.current_revision(conn)
            counted = conn.execute(_COUNTS).mappings().one()
        return {
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "schema_version": runner.revision_count("board"),
            "schema_revision": revision,
            "counts": {table: int(counted[table]) for table in _COUNTED_TABLES},
        }
