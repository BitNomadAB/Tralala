"""A revision may rebuild a table others reference: its children survive, a broken key rolls back.

``runner.migration_transaction`` follows SQLite's table-rebuild procedure: foreign keys off before
the transaction starts, ``PRAGMA foreign_key_check`` before the COMMIT, foreign keys back on after
it. With foreign keys on, the DROP of the old copy would delete the CASCADE children and clear the
links a table holds to itself. Which rows a refusal names is unit-tested in
``tests/unit/test_integrity.py``. The test runs on the session's board database, on two tables of
its own, and leaves it as it found it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.storage.board_db import BoardDatabaseManager
from app.storage.schema import runner
from app.storage.sqlite import write_transaction

_SCHEMA = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
_PARENTS = "SELECT id, previous_id FROM rebuild_parent ORDER BY id"
_CHILDREN = "SELECT id, parent_id FROM rebuild_child ORDER BY id"
_KEYS = 'SELECT "table", "from", on_delete FROM pragma_foreign_key_list(\'rebuild_parent\')'


def _read(engine: Engine, query: str) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(query)]


@pytest.fixture
def board_engine(boards: BoardDatabaseManager, board_id: str) -> Iterator[Engine]:
    """The board's own engine with two tables of the test's: a parent and its CASCADE children."""
    with boards.locked(board_id):
        engine = boards.open(board_id)
        with write_transaction(engine) as connection:
            connection.exec_driver_sql(
                "CREATE TABLE rebuild_parent (id TEXT PRIMARY KEY, previous_id TEXT)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE rebuild_child (id TEXT PRIMARY KEY, parent_id TEXT NOT NULL"
                " REFERENCES rebuild_parent (id) ON DELETE CASCADE)"
            )
            connection.exec_driver_sql(
                "INSERT INTO rebuild_parent VALUES ('p1', NULL), ('p2', 'p1')"
            )
            connection.exec_driver_sql(
                "INSERT INTO rebuild_child VALUES ('c1', 'p1'), ('c2', 'p2')"
            )
        try:
            yield engine
        finally:
            with write_transaction(engine) as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS rebuild_child")
                connection.exec_driver_sql("DROP TABLE IF EXISTS rebuild_parent")
                connection.exec_driver_sql("DROP TABLE IF EXISTS _alembic_tmp_rebuild_parent")


def test_a_rebuilt_parent_keeps_its_children_and_a_broken_key_rolls_the_change_back(
    board_engine: Engine,
) -> None:
    # What each migration connection says about foreign keys as it goes back to the pool, which
    # closes it right after: the transaction must have turned them back on.
    returned: list[int] = []

    def _on_checkin(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        returned.append(dbapi_connection.execute("PRAGMA foreign_keys").fetchone()[0])

    event.listen(board_engine, "checkin", _on_checkin)
    try:
        # A revision gives the parent a key to itself: the table rebuild_child references
        # (CASCADE) is rebuilt, and its rows link to each other.
        with runner.migration_transaction(board_engine) as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 0
            op = Operations(MigrationContext.configure(connection))
            with op.batch_alter_table("rebuild_parent", recreate="always") as batch:
                batch.create_foreign_key(
                    "fk_rebuild_parent_previous",
                    "rebuild_parent",
                    ["previous_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        assert returned == [1]
    finally:
        event.remove(board_engine, "checkin", _on_checkin)

    assert _read(board_engine, _CHILDREN) == [("c1", "p1"), ("c2", "p2")]
    assert _read(board_engine, _PARENTS) == [("p1", None), ("p2", "p1")]
    assert _read(board_engine, _KEYS) == [("rebuild_parent", "previous_id", "SET NULL")]
    schema = _read(board_engine, _SCHEMA)
    assert [row for row in schema if str(row[1]).startswith("_alembic_tmp_")] == []

    # A change whose DDL succeeds but that leaves a row naming a missing one is refused before
    # its COMMIT, and nothing of it remains.
    with (
        pytest.raises(
            runner.ForeignKeyCheckError, match=r"rebuild_child rowid \d+ -> rebuild_parent"
        ),
        runner.migration_transaction(board_engine) as connection,
    ):
        connection.exec_driver_sql("CREATE INDEX ix_rebuild_parent_previous ON rebuild_parent (id)")
        connection.exec_driver_sql("INSERT INTO rebuild_child VALUES ('c3', 'missing')")

    assert _read(board_engine, _SCHEMA) == schema
    assert _read(board_engine, _CHILDREN) == [("c1", "p1"), ("c2", "p2")]
