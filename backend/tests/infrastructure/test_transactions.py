"""The engine's BEGIN on a real file: DDL rolls back, and a second writer waits for the first.

``core/transactions.py`` explains the recipe; ``tests/unit/test_transactions.py`` pins the
statements the listener sends. Both tests run on the session's board database and leave it as
they found it.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.storage.board_db import BoardDatabaseManager
from app.storage.schema import runner
from app.storage.sqlite import create_sqlite_engine, write_transaction

_INSERT = text("INSERT INTO infrastructure_probe (value) VALUES (:value)")
_COUNT = text("SELECT COUNT(*) FROM infrastructure_probe")
_SCHEMA = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
WAIT_SECONDS = 10


def _schema(engine: Engine) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(_SCHEMA)]


@pytest.fixture
def board_engine(boards: BoardDatabaseManager, board_id: str) -> Iterator[Engine]:
    """The board's own engine, with the board held so nothing else in the process opens it."""
    with boards.locked(board_id):
        yield boards.open(board_id)


def test_a_revision_that_fails_after_its_ddl_leaves_the_schema_as_it_was(
    board_engine: Engine,
) -> None:
    before = _schema(board_engine)
    try:
        with (
            pytest.raises(OperationalError, match="no such table"),
            runner.migration_transaction(board_engine) as connection,
        ):
            # What a revision does through ``op``: new table, index, then a statement that fails.
            op = Operations(MigrationContext.configure(connection))
            op.create_table(
                "ddl_probe",
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("value", sa.Text, nullable=False),
            )
            op.create_index("ix_ddl_probe_value", "ddl_probe", ["value"])
            op.execute("INSERT INTO ddl_probe_missing (value) VALUES ('x')")

        assert _schema(board_engine) == before
    finally:
        # Only does anything when DDL escaped the transaction, so later tests see a clean board.
        with write_transaction(board_engine) as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS ddl_probe")


@pytest.mark.usefixtures("probe")
def test_a_second_writer_waits_at_its_begin_and_reads_what_the_first_committed(
    boards: BoardDatabaseManager, board_id: str
) -> None:
    path = boards.path(board_id)
    first_engine = create_sqlite_engine(path)
    second_engine = create_sqlite_engine(path)
    second_sent_begin = threading.Event()
    second_holds_lock = threading.Event()
    outcome: dict[str, object] = {}

    @event.listens_for(second_engine, "connect")
    def _watch_begin(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        # SQLite reports a statement as it starts to run, before BEGIN IMMEDIATE takes the lock.
        def trace(statement: str) -> None:
            if statement == "BEGIN IMMEDIATE":
                second_sent_begin.set()

        dbapi_connection.set_trace_callback(trace)

    def second_writer() -> None:
        try:
            with write_transaction(second_engine) as connection:
                second_holds_lock.set()
                outcome["rows_seen"] = connection.execute(_COUNT).scalar_one()
                connection.execute(_INSERT, {"value": "second"})
        except Exception as exc:  # noqa: BLE001 - reported by the assertion below
            outcome["error"] = repr(exc)

    second = threading.Thread(target=second_writer, name="second-writer")
    try:
        with boards.locked(board_id), write_transaction(first_engine) as connection:
            connection.execute(_INSERT, {"value": "first"})
            second.start()
            assert second_sent_begin.wait(WAIT_SECONDS)
            # The first writer still holds the write lock, so the second cannot be past its BEGIN.
            assert not second_holds_lock.is_set()
        second.join(WAIT_SECONDS)
        assert not second.is_alive()
    finally:
        first_engine.dispose()
        second_engine.dispose()

    assert outcome == {"rows_seen": 1}
    with boards.reader(board_id) as connection:
        values = connection.execute(text("SELECT value FROM infrastructure_probe")).scalars()
        assert sorted(values) == ["first", "second"]
