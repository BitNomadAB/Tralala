"""The migrations run to completion on a real file, and a second run finds nothing to do."""

from __future__ import annotations

from app.storage.board_db import BoardDatabaseManager
from app.storage.migration_manager import MigrationManager, MigrationReport
from app.storage.registry import Registry
from app.storage.schema import runner


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
