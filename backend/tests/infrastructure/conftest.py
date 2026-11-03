"""The minimal infrastructure suite: one real SQLite data directory for the whole session.

These tests check only what a fake cannot: that connections are initialised, that the migrations
run to completion, that the unit of work commits and rolls back, that a closed board lets go of its
file and that the databases answer. They never test business rules, tables or columns (the unit
suite and ``python -m tools.dbgen`` do that). The registry and one board are migrated once per
session (per worker under pytest-xdist) into a real file, not ``:memory:``, so WAL, file locks and
handle release are the real ones; each test cleans up what it wrote, and the directory goes with the
session.

Run separately: ``python -m pytest tests/infrastructure``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text

from app.core.config import Settings
from app.db import freshness
from app.repositories.sql.board import SqlBoardUnitOfWork
from app.storage.board_db import BoardDatabaseManager
from app.storage.migration_manager import MigrationManager, MigrationReport
from app.storage.registry import Registry
from app.storage.schema import runner


def pytest_sessionstart(session: pytest.Session) -> None:
    """Stop before collecting when the rows were generated from another schema."""
    del session
    problem = freshness.problem()
    if problem is not None:
        pytest.exit(problem, returncode=1)


BOARD_ID = "5d0c6c8e-2b1f-4e57-9a3d-7c4b1e2f6a90"
SECRET = "infrastructure-test-installation-secret-" + "s" * 24


class InfrastructureSettings(Settings):
    """The application's settings without a `.env` file."""

    model_config = SettingsConfigDict(env_file=None)


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = InfrastructureSettings(
        data_dir=tmp_path_factory.mktemp("data"), secret_key=SECRET
    )
    settings.ensure_dirs()
    return settings


@pytest.fixture(scope="session")
def registry(settings: Settings) -> Iterator[Registry]:
    registry = Registry(settings)
    yield registry
    registry.dispose()


@pytest.fixture(scope="session")
def boards(settings: Settings) -> Iterator[BoardDatabaseManager]:
    manager = BoardDatabaseManager(settings)
    yield manager
    manager.close_all()


@pytest.fixture(scope="session")
def migrations(
    settings: Settings, registry: Registry, boards: BoardDatabaseManager
) -> MigrationManager:
    return MigrationManager(settings, registry, boards)


@pytest.fixture(scope="session")
def first_migration(
    migrations: MigrationManager, registry: Registry, boards: BoardDatabaseManager
) -> MigrationReport:
    """The registry migrated from nothing, and one board created at the head of its chain."""
    report = migrations.migrate_registry()
    registry.insert_board(BOARD_ID, "Infrastructure", "", "active", runner.revision_count("board"))
    boards.create_database(BOARD_ID)
    return report


@pytest.fixture(scope="session")
def board_id(first_migration: MigrationReport) -> str:
    del first_migration
    return BOARD_ID


@pytest.fixture(scope="session")
def store(boards: BoardDatabaseManager) -> SqlBoardUnitOfWork:
    return SqlBoardUnitOfWork(boards)


@pytest.fixture(scope="session")
def probe_table(boards: BoardDatabaseManager, board_id: str) -> Iterator[str]:
    """A table no migration knows: the unit of work is proven on it, never on a model table.

    Not a TEMP table: that lives only as long as its connection, and the board store opens a new
    connection for every reader and writer (NullPool, a deliberate bound on open handles), so a TEMP
    table could never show what a finished writer left behind.
    """
    with boards.session(board_id) as connection:
        connection.execute(text("CREATE TABLE infrastructure_probe (value TEXT NOT NULL)"))
    yield "infrastructure_probe"
    with boards.session(board_id) as connection:
        connection.execute(text("DROP TABLE infrastructure_probe"))


@pytest.fixture
def probe(boards: BoardDatabaseManager, board_id: str, probe_table: str) -> Iterator[str]:
    """The probe table, emptied again after the test."""
    yield probe_table
    with boards.session(board_id) as connection:
        connection.execute(text("DELETE FROM infrastructure_probe"))
