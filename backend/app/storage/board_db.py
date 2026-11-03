from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from ..core.config import Settings
from ..core.errors import BoardUnreadable, NotFound, ServiceUnavailable
from ..core.identifiers import canonical_board_id
from ..core.platform import remove_tree
from .schema import ensure_fts, runner
from .sqlite import (
    close_maintenance,
    create_sqlite_engine,
    snapshot_database,
    utcnow,
    write_transaction,
)

MAX_CACHED_BOARDS = 64

logger = logging.getLogger("tralala")

# SQLite's answers about the file itself: it is not a database, or it is damaged. Retrying cannot
# help, unlike a busy or locked database.
UNREADABLE_CODES = frozenset({sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT})


@contextmanager
def _readable() -> Iterator[None]:
    """SQLite refusing a board's file, raised as ``BoardUnreadable`` instead of a driver error.

    Callers that step past a board they cannot open (the board list's counters, startup recovery,
    the discussions overview) catch ``ServiceUnavailable``, so one damaged file never fails them,
    and a request for that board answers ``503 board_database_unreadable`` instead of a 500.
    """
    try:
        yield
    except DBAPIError as exc:
        original = exc.orig
        if not isinstance(original, sqlite3.Error):
            raise
        if original.sqlite_errorcode & 0xFF not in UNREADABLE_CODES:
            raise
        raise BoardUnreadable(
            "Board database cannot be read",
            details={"sqlite_error": original.sqlite_errorname},
        ) from exc


class BoardDatabaseManager:
    """Owns per-board SQLite engines, migrations and bounded connection lifetimes.

    A board id is always a UUID and is mapped through this manager, so no caller can
    construct a database path from user-controlled text.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engines: dict[str, Engine] = {}
        self._last_used: dict[str, float] = {}
        self._verified: set[str] = set()
        self._fts: dict[str, bool] = {}
        self._lock = RLock()
        self._board_locks: dict[str, RLock] = {}
        # Called after a committed write, and after closing or deleting a board, so a cache of
        # derived board content can be dropped from one place instead of every service.
        self.on_write: Callable[[str], None] | None = None

    def _notify_write(self, board_id: str) -> None:
        hook = self.on_write
        if hook is not None:
            hook(board_id)

    @staticmethod
    def validate_board_id(board_id: str) -> str:
        return canonical_board_id(board_id)

    def path(self, board_id: str) -> Path:
        return self.settings.boards_dir / self.validate_board_id(board_id) / "board.sqlite"

    def attachments_dir(self, board_id: str) -> Path:
        """Where one board's uploaded files live; the database and its files are one unit."""
        return self.settings.boards_dir / self.validate_board_id(board_id) / "attachments"

    def snapshot(self, board_id: str, target: Path) -> None:
        """A consistent copy of the board's database at ``target`` (SQLite's online backup)."""
        snapshot_database(self.path(board_id), target)

    def exists(self, board_id: str) -> bool:
        try:
            return self.path(board_id).exists()
        except NotFound:
            return False

    def create_database(self, board_id: str, description: str = "") -> None:
        self.validate_board_id(board_id)
        engine = create_sqlite_engine(self.path(board_id))
        runner.create_schema("board", engine)
        self._fts[board_id] = ensure_fts(engine)
        now = utcnow()
        with write_transaction(engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO board_metadata (id, description, created_at, updated_at,"
                    " schema_version) VALUES (:id, :description, :now, :now, :version)"
                ),
                {
                    "id": board_id,
                    "description": description,
                    "now": now,
                    "version": runner.revision_count("board"),
                },
            )
        self._engines[board_id] = engine
        self._last_used[board_id] = time.monotonic()
        self._verified.add(board_id)

    def _board_lock(self, board_id: str) -> RLock:
        with self._lock:
            return self._board_locks.setdefault(self.validate_board_id(board_id), RLock())

    @contextmanager
    def locked(self, board_id: str) -> Iterator[None]:
        """Exclusive access to one board, shared by readers, writers and restore.

        The lock is re-entrant, so nested ``open``/``session`` calls from the same thread are
        safe. It serializes access inside this process; cross-process coordination still
        requires a single backend instance per data directory.
        """
        with self._board_lock(board_id):
            yield

    def open(self, board_id: str) -> Engine:
        self.validate_board_id(board_id)
        released: list[str] = []
        try:
            return self._open(board_id, released)
        finally:
            # Once the manager's lock is released: upkeep of the boards this open let go must not
            # hold up every other board's open.
            self._maintain(released)

    def _open(self, board_id: str, released: list[str]) -> Engine:
        """``open`` itself; the boards it lets go (idle or over the cap) go into ``released``."""
        with self._board_lock(board_id), self._lock:
            released.extend(self._sweep())
            engine = self._engines.get(board_id)
            if engine is None:
                path = self.path(board_id)
                if not path.exists():
                    # A registry row without its database is an integrity event, not a normal 404.
                    logger.error(
                        "board_database_missing", extra={"board_id": board_id, "path": str(path)}
                    )
                    raise NotFound("Board database not found")
                engine = create_sqlite_engine(path)
                self._engines[board_id] = engine
            self._last_used[board_id] = time.monotonic()
            if board_id not in self._verified:
                try:
                    with _readable(), engine.connect() as connection:
                        current = runner.current_revision(connection)
                except BoardUnreadable:
                    self._drop(board_id, engine)
                    raise
                head = runner.head_revision("board")
                if current != head:
                    self._drop(board_id, engine)
                    raise ServiceUnavailable(
                        "Board schema is not at the current revision",
                        code="board_schema_outdated",
                        details={"current_revision": current, "head_revision": head},
                    )
                self._verified.add(board_id)
            released.extend(self._evict_overflow())
            return engine

    def _drop(self, board_id: str, engine: Engine) -> None:
        """Forget an engine that failed its check, so the next open looks at the file again."""
        self._engines.pop(board_id, None)
        self._last_used.pop(board_id, None)
        engine.dispose()

    def fts_available(self, board_id: str) -> bool:
        if board_id not in self._fts:
            engine = self.open(board_id)
            self._fts[board_id] = ensure_fts(engine)
        return self._fts[board_id]

    @contextmanager
    def session(self, board_id: str) -> Iterator[Connection]:
        """Single transactional unit of work against one board database."""
        with self._board_lock(board_id):
            engine = self.open(board_id)
            with _readable(), write_transaction(engine) as conn:
                yield conn
            with self._lock:
                self._last_used[board_id] = time.monotonic()
            self._notify_write(board_id)

    @contextmanager
    def reader(self, board_id: str) -> Iterator[Connection]:
        with self._board_lock(board_id):
            engine = self.open(board_id)
            with _readable(), engine.connect() as conn:
                yield conn

    def close(self, board_id: str) -> None:
        # Restoring a backup closes the board and replaces the file, which no transaction reports.
        self._notify_write(board_id)
        with self._board_lock(board_id), self._lock:
            engine = self._engines.pop(board_id, None)
            self._last_used.pop(board_id, None)
            self._verified.discard(board_id)
            self._fts.pop(board_id, None)
            if engine is not None:
                engine.dispose()

    def delete_database(self, board_id: str) -> None:
        """Remove everything this board owns: its database and its uploaded files.

        The directory is the unit, because a board is a database plus its attachments. Removing only
        the SQLite files used to fail on ``rmdir`` as soon as an attachment existed, which left the
        row behind with no database to open.

        A host that holds a file open (Windows, or a network share) is retried briefly, because that
        clears on its own. Anything else raises so the caller can keep the registry row and report
        the leftover directory instead of pretending the board is gone.
        """
        self.close(board_id)
        directory = self.path(board_id).parent
        remove_tree(directory, profile=self.settings.file_profile)

    def close_all(self) -> None:
        """Release every board at shutdown, then look after each one (``_maintain``)."""
        with self._lock:
            released = list(self._engines)
            for engine in self._engines.values():
                engine.dispose()
            self._engines.clear()
            self._last_used.clear()
            self._verified.clear()
            self._fts.clear()
        self._maintain(released)

    def _sweep(self) -> list[str]:
        """Release the boards idle longer than the setting; the caller maintains them."""
        cutoff = time.monotonic() - self.settings.board_idle_close_seconds
        return [
            board_id
            for board_id, used in list(self._last_used.items())
            if used < cutoff and self._release(board_id)
        ]

    def _evict_overflow(self) -> list[str]:
        """Release the least recently used boards beyond the cap; the caller maintains them."""
        if len(self._engines) <= MAX_CACHED_BOARDS:
            return []
        oldest = sorted(self._last_used.items(), key=lambda item: item[1])
        return [
            board_id
            for board_id, _ in oldest[: len(self._engines) - MAX_CACHED_BOARDS]
            if self._release(board_id)
        ]

    def _release(self, board_id: str) -> bool:
        """Forget a board's engine (the caller holds ``_lock``); whether it had one."""
        engine = self._engines.pop(board_id, None)
        self._last_used.pop(board_id, None)
        self._verified.discard(board_id)
        self._fts.pop(board_id, None)
        if engine is None:
            return False
        engine.dispose()
        return True

    def _maintain(self, board_ids: Iterable[str]) -> None:
        """SQLite's upkeep for boards that went out of use: ``CLOSE_PRAGMAS`` (``core/pragmas.py``).

        Only where a board goes out of use with its file staying as it is: the idle sweep, the
        eviction of the least recently used board and shutdown. ``close`` does not maintain: it is
        called right before a restore, a migration or a delete changes or removes the file. Best
        effort: a board SQLite will not open or that is busy just now is skipped and logged.
        """
        for board_id in board_ids:
            try:
                close_maintenance(self.path(board_id))
            except sqlite3.Error as exc:
                logger.info(
                    "board_maintenance_skipped",
                    extra={
                        "board_id": board_id,
                        "sqlite_error": getattr(exc, "sqlite_errorname", None),
                    },
                )
