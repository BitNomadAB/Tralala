"""Connections are initialised and the migrations run to completion on a real file."""

from __future__ import annotations

from app.core.config import Settings
from app.core.pragmas import JOURNAL_SIZE_LIMIT_BYTES
from app.storage.board_db import BoardDatabaseManager
from app.storage.migration_manager import MigrationManager, MigrationReport
from app.storage.registry import Registry
from app.storage.schema import runner
from app.storage.sqlite import BUSY_TIMEOUT_MS, connect_sqlite, create_sqlite_engine


def test_every_engine_connection_gets_the_pragmas(settings: Settings, board_id: str) -> None:
    engine = create_sqlite_engine(settings.boards_dir / board_id / "board.sqlite")
    try:
        with engine.connect() as connection:
            pragmas = {
                name: connection.exec_driver_sql(f"PRAGMA {name}").scalar_one()
                for name in (
                    "foreign_keys",
                    "journal_mode",
                    "busy_timeout",
                    "synchronous",
                    "journal_size_limit",
                )
            }
    finally:
        engine.dispose()
    # synchronous=NORMAL reads back as 1.
    assert pragmas == {
        "foreign_keys": 1,
        "journal_mode": "wal",
        "busy_timeout": BUSY_TIMEOUT_MS,
        "synchronous": 1,
        "journal_size_limit": JOURNAL_SIZE_LIMIT_BYTES,
    }


def test_the_backup_connection_enforces_foreign_keys_and_waits(
    settings: Settings, board_id: str
) -> None:
    connection = connect_sqlite(settings.boards_dir / board_id / "board.sqlite")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (BUSY_TIMEOUT_MS,)
    finally:
        connection.close()


def test_both_chains_migrate_to_their_head(
    first_migration: MigrationReport,
    registry: Registry,
    boards: BoardDatabaseManager,
    board_id: str,
) -> None:
    assert (first_migration.status, first_migration.from_revision) == ("migrated", None)
    assert first_migration.to_revision == runner.head_revision("registry")
    with registry.engine.connect() as connection:
        assert runner.current_revision(connection) == runner.head_revision("registry")
    with boards.reader(board_id) as connection:
        assert runner.current_revision(connection) == runner.head_revision("board")


def test_a_second_run_finds_both_chains_up_to_date(
    migrations: MigrationManager, board_id: str
) -> None:
    registry_report = migrations.migrate_registry()
    board_report = migrations.migrate_board(board_id)

    assert (registry_report.status, board_report.status) == ("up_to_date", "up_to_date")
    assert board_report.to_revision == runner.head_revision("board")
