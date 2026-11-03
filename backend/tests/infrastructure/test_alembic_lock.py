"""Two board databases migrate at once, the second Alembic command after the first.

``app/storage/schema/runner.py`` explains why Alembic commands run one at a time, and
``tests/unit/test_alembic_lock.py`` guards that every one does. Here two threads create a board
database each, as two board creations in two requests do. The first is held inside its migration,
where Alembic's ``context`` and ``op`` globals are installed, until the second has reached the lock;
then both must finish at the head of the chain. A migration needs a database that is not at head
yet, so this test creates its two files in its own temporary directory instead of using the
session's board.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest
from sqlalchemy import event

from app.storage.schema import runner
from app.storage.sqlite import create_sqlite_engine

WAIT_SECONDS = 10


class WatchedLock:
    """The runner's lock, reporting when a command found it held and had to wait."""

    def __init__(self, waited: threading.Event) -> None:
        self._lock = threading.Lock()
        self._waited = waited

    def __enter__(self) -> None:
        if not self._lock.acquire(blocking=False):
            self._waited.set()
            self._lock.acquire()

    def __exit__(self, *exc_info: object) -> None:
        self._lock.release()


def test_two_board_databases_migrate_at_once_one_command_after_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_inside = threading.Event()
    release_first = threading.Event()
    second_waited = threading.Event()
    monkeypatch.setattr(runner, "_ALEMBIC_LOCK", WatchedLock(second_waited))
    engines = {
        name: create_sqlite_engine(tmp_path / name / "board.sqlite") for name in ("first", "second")
    }
    outcome: dict[str, str] = {}

    @event.listens_for(engines["first"], "connect")
    def _hold_first(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        def trace(statement: str) -> None:
            # The first table of a run (alembic_version) is created while the globals are installed.
            if statement.lstrip().startswith("CREATE TABLE") and not first_inside.is_set():
                first_inside.set()
                release_first.wait(WAIT_SECONDS)

        dbapi_connection.set_trace_callback(trace)

    def migrate(name: str) -> None:
        try:
            outcome[name] = runner.create_schema("board", engines[name])
        except Exception as exc:  # noqa: BLE001 - reported by the assertion below
            outcome[name] = repr(exc)

    threads = [threading.Thread(target=migrate, args=(name,), name=name) for name in engines]
    try:
        try:
            threads[0].start()
            assert first_inside.wait(WAIT_SECONDS)
            threads[1].start()
            # The second command reaches the lock while the first is still inside its revisions.
            assert second_waited.wait(WAIT_SECONDS)
        finally:
            release_first.set()
            for thread in threads:
                if thread.ident is not None:  # started
                    thread.join(WAIT_SECONDS)

        head = runner.head_revision("board")
        assert not any(thread.is_alive() for thread in threads)
        assert outcome == {"first": head, "second": head}
        for engine in engines.values():
            with engine.connect() as connection:
                assert runner.current_revision(connection) == head
    finally:
        for engine in engines.values():
            engine.dispose()
