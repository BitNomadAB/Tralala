from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

# Re-exported: the clock moved to core so a service can take it without importing storage.
from ..core.dates import utcnow as utcnow
from ..core.integrity import (
    SnapshotProblem,
    integrity_problem,
    snapshot_problem,
    unreadable_problem,
)
from ..core.pragmas import (
    AFTER_RESTORE_PRAGMAS,
    CLOSE_PRAGMAS,
    CONNECT_PRAGMAS,
    FOREIGN_KEY_CHECK,
    INTEGRITY_CHECK,
)

# Re-exported: the PRAGMA lists that use it live in core, where the unit suite can read them.
from ..core.pragmas import BUSY_TIMEOUT_MS as BUSY_TIMEOUT_MS
from ..core.transactions import WRITER, begin_transaction

_FOREIGN_KEYS_STATE = "PRAGMA foreign_keys"
_FOREIGN_KEYS_OFF = "PRAGMA foreign_keys=OFF"
_FOREIGN_KEYS_ON = "PRAGMA foreign_keys=ON"


def create_sqlite_engine(path: Path) -> Engine:
    """One engine per database file. NullPool keeps the number of open handles bounded.

    The driver's own BEGIN is off (``isolation_level=None``) and ``begin_transaction`` sends every
    BEGIN, so DDL is transactional and a writer takes the write lock at its BEGIN
    (``core/transactions.py``). ``busy_timeout`` is how long a BEGIN IMMEDIATE waits for it. Every
    connection sends ``CONNECT_PRAGMAS`` first (``core/pragmas.py``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite+pysqlite:///{path.as_posix()}",
        future=True,
        poolclass=NullPool,
        connect_args={
            "timeout": BUSY_TIMEOUT_MS / 1000,
            "check_same_thread": False,
            "isolation_level": None,
        },
    )
    event.listen(engine, "begin", begin_transaction)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        for statement in CONNECT_PRAGMAS:
            dbapi_connection.execute(statement)

    return engine


def close_maintenance(path: Path) -> None:
    """Send ``CLOSE_PRAGMAS`` to the database at ``path`` on a connection of their own.

    For a board that went out of use (``BoardDatabaseManager``). Its engine is gone, but another
    connection may still use the file (a backup being taken, a request that opened the board again
    since). So the connection never creates the file (``mode=rw``) and never waits (no busy
    timeout): upkeep runs on the path of whichever request let the board go, and a board that is
    busy just now is skipped and looked after the next time. Raises ``sqlite3.Error``; the caller
    logs it and carries on.
    """
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=0, isolation_level=None
    )
    try:
        for statement in CLOSE_PRAGMAS:
            connection.execute(statement).fetchall()
    finally:
        connection.close()


@contextmanager
def write_transaction(engine: Engine) -> Iterator[Connection]:
    """``engine.begin()`` for a transaction that writes: it starts with ``BEGIN IMMEDIATE``.

    Committed when the block ends and rolled back when it raises, as ``engine.begin()`` is. A
    transaction that only reads uses ``engine.connect()`` and starts with a deferred ``BEGIN``.
    """
    with engine.connect() as connection, _immediate(connection):
        yield connection


@contextmanager
def _immediate(connection: Connection) -> Iterator[None]:
    """The one place a transaction is begun by hand: as a writer, so ``BEGIN IMMEDIATE``."""
    connection.execution_options(**{WRITER: True})
    with connection.begin():
        yield


@contextmanager
def schema_change_transaction(engine: Engine) -> Iterator[Connection]:
    """A ``write_transaction`` with foreign key enforcement off, for a schema change.

    SQLite rebuilds a table to change it (https://www.sqlite.org/lang_altertable.html, "Making Other
    Kinds Of Table Schema Changes"), and dropping the old copy with foreign keys on fires the ON
    DELETE action of every row that references it: CASCADE deletes the children, SET NULL clears
    them, RESTRICT fails. The procedure therefore turns enforcement off before the transaction
    starts (step 1), because ``PRAGMA foreign_keys`` is a no-op inside one, and back on after it
    ends (step 12). The caller checks the keys before the COMMIT (step 10):
    ``runner.migration_transaction`` does.

    Both pragmas go to the driver's connection: a statement sent through SQLAlchemy would begin
    the transaction first (``core/transactions.py``). The setting is put back as it was found.
    """
    with engine.connect() as connection:
        driver = connection.connection.driver_connection
        if driver is None:
            raise RuntimeError("The SQLite connection has no driver connection")
        enforced = driver.execute(_FOREIGN_KEYS_STATE).fetchone()[0] == 1
        driver.execute(_FOREIGN_KEYS_OFF)
        try:
            with _immediate(connection):
                yield connection
        finally:
            if enforced and not connection.invalidated:
                driver.execute(_FOREIGN_KEYS_ON)


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


def check_snapshot(path: Path) -> SnapshotProblem | None:
    """None when the snapshot at ``path`` may be restored, else why not.

    It is read as ``connect_untrusted`` reads a file (read only, ``immutable``: nothing is written
    beside it), as ``restore_snapshot`` will read it. ``integrity_check`` runs first and
    ``foreign_key_check`` only on a file that passed it; ``core/integrity.py`` judges the rows, and
    an error SQLite raises on the way (a damaged page, not a database) is a refusal too.
    """
    try:
        connection = connect_untrusted(path)
    except sqlite3.Error as exc:
        return unreadable_problem(_error_code(exc), str(exc))
    try:
        findings = connection.execute(INTEGRITY_CHECK).fetchall()
        violations = (
            connection.execute(FOREIGN_KEY_CHECK).fetchall()
            if integrity_problem(findings) is None
            else []
        )
        return snapshot_problem(findings, violations)
    except sqlite3.Error as exc:
        return unreadable_problem(_error_code(exc), str(exc))
    finally:
        connection.close()


def _error_code(error: sqlite3.Error) -> int:
    """SQLite's extended result code, or 0 for an error the driver raised itself."""
    code: int | None = getattr(error, "sqlite_errorcode", None)
    return code or 0


def restore_snapshot(source: Path, target: Path) -> None:
    """Copy a snapshot ``check_snapshot`` accepted over a board's database, with the backup API.

    The snapshot is read exactly as it was checked (``connect_untrusted``), so the pages copied are
    the pages checked, and the copy is one transaction on the target: a failure leaves the board's
    previous database. The target is in WAL mode, so the copy lands in its ``-wal`` file;
    ``AFTER_RESTORE_PRAGMAS`` moves it into the database file at once, also when another connection
    still has the file open, in which case SQLite's own checkpoint would come only when the last
    connection closes.
    """
    src = connect_untrusted(source)
    try:
        dst = sqlite3.connect(target, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            src.backup(dst)
            for statement in AFTER_RESTORE_PRAGMAS:
                dst.execute(statement).fetchall()
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
