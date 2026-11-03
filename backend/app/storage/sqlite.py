from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

# Re-exported: the clock moved to core so a service can take it without importing storage.
from ..core.dates import utcnow as utcnow

BUSY_TIMEOUT_MS = 5000


def create_sqlite_engine(path: Path) -> Engine:
    """One engine per database file. NullPool keeps the number of open handles bounded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{path.as_posix()}",
        future=True,
        poolclass=NullPool,
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        dbapi_connection.execute("PRAGMA synchronous=NORMAL")

    return engine


def connect_sqlite(path: Path) -> sqlite3.Connection:
    """Direct sqlite3 connection used for backup/restore snapshots."""
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return connection


def connect_untrusted(path: Path) -> sqlite3.Connection:
    """A read-only connection to a database file this installation did not write (an import).

    Set up as SQLite's advice for database files of unknown origin says
    (https://www.sqlite.org/security.html): the schema is not trusted, triggers and views are off so
    nothing stored in the file can run, defensive mode, ``cell_size_check`` on and no memory-mapped
    I/O. The caller runs ``PRAGMA integrity_check`` before anything else. ``immutable=1`` because
    the file was just written and nothing else has it: no locks, and no ``-wal``/``-shm`` files are
    created beside it.
    """
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_VIEW, False)
        connection.execute("PRAGMA cell_size_check=ON")
        connection.execute("PRAGMA mmap_size=0")
    except BaseException:
        connection.close()
        raise
    return connection


def snapshot_database(source: Path, target: Path) -> None:
    """Create a transactionally consistent copy using SQLite's online backup API."""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


@lru_cache(maxsize=1)
def sqlite_supports_fts5() -> bool:
    """True when the SQLite build can create FTS5 virtual tables."""
    try:
        with sqlite3.connect(":memory:") as probe:
            probe.execute("CREATE VIRTUAL TABLE probe USING fts5(value)")
    except sqlite3.Error:
        return False
    return True
