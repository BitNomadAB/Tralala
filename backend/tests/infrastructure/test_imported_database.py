"""A file that is not a database is refused before anything opens it as a board.

The only infrastructure test of the import check (the rules are unit-tested on fakes): it needs the
real SQLite to show that the read-only, untrusted connection refuses such a file, writes nothing
beside it, still reads a real board's snapshot (an export, flagged WAL), and that a board opened on
such a file answers ``BoardUnreadable`` instead of a driver error.
"""

from __future__ import annotations

import pytest

from app.core.errors import BoardUnreadable
from app.repositories.board_files import DatabaseProblem
from app.storage.board_db import BoardDatabaseManager
from app.storage.migration_manager import MigrationManager

STRANGER = "5d0c6c8e-2b1f-4e57-9a3d-00000000a27a"


def test_a_file_that_is_not_a_database_is_refused_and_never_opened_as_a_board(
    boards: BoardDatabaseManager, migrations: MigrationManager, board_id: str
) -> None:
    path = boards.path(STRANGER)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not sqlite at all" * 40)
    try:
        assert migrations.check_imported(STRANGER) == DatabaseProblem(
            reason="not_a_database", detail="file is not a database"
        )
        assert [file.name for file in path.parent.iterdir()] == ["board.sqlite"]
        with pytest.raises(BoardUnreadable), boards.reader(STRANGER):
            pass

        path.unlink()
        boards.snapshot(board_id, path)
        assert migrations.check_imported(STRANGER) is None
        assert [file.name for file in path.parent.iterdir()] == ["board.sqlite"]
    finally:
        boards.delete_database(STRANGER)
