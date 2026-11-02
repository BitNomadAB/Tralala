from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..core.config import Settings
from ..core.errors import NotFound, ServiceUnavailable
from ..core.platform import remove_tree
from .schema import ensure_fts, runner
from .sqlite import create_sqlite_engine, utcnow

MAX_CACHED_BOARDS = 64

logger = logging.getLogger("tralala")


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

    @staticmethod
    def validate_board_id(board_id: str) -> str:
        try:
            return str(uuid.UUID(board_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise NotFound("Board not found") from exc

    def path(self, board_id: str) -> Path:
        return self.settings.boards_dir / self.validate_board_id(board_id) / "board.sqlite"

    def attachments_dir(self, board_id: str) -> Path:
        """Where one board's uploaded files live; the database and its files are one unit."""
        return self.settings.boards_dir / self.validate_board_id(board_id) / "attachments"

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
        with engine.begin() as conn:
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
        with self._board_lock(board_id), self._lock:
            self._sweep()
            engine = self._engines.get(board_id)
            if engine is None:
                path = self.path(board_id)
                if not path.exists():
                    # A registry row without its database is an integrity event, not a normal 404.
                    logger.error(
                        json.dumps(
                            {
                                "event": "board_database_missing",
                                "board_id": board_id,
                                "path": str(path),
                            }
                        )
                    )
                    raise NotFound("Board database not found")
                engine = create_sqlite_engine(path)
                self._engines[board_id] = engine
            self._last_used[board_id] = time.monotonic()
            if board_id not in self._verified:
                with engine.connect() as connection:
                    current = runner.current_revision("board", connection)
                head = runner.head_revision("board")
                if current != head:
                    self._engines.pop(board_id, None)
                    self._last_used.pop(board_id, None)
                    engine.dispose()
                    raise ServiceUnavailable(
                        "Board schema is not at the current revision",
                        code="board_schema_outdated",
                        details={"current_revision": current, "head_revision": head},
                    )
                self._verified.add(board_id)
            self._evict_overflow()
            return engine

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
            with engine.begin() as conn:
                yield conn
            with self._lock:
                self._last_used[board_id] = time.monotonic()

    @contextmanager
    def reader(self, board_id: str) -> Iterator[Connection]:
        with self._board_lock(board_id):
            engine = self.open(board_id)
            with engine.connect() as conn:
                yield conn

    def close(self, board_id: str) -> None:
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
        with self._lock:
            for engine in self._engines.values():
                engine.dispose()
            self._engines.clear()
            self._last_used.clear()
            self._verified.clear()
            self._fts.clear()

    def _sweep(self) -> None:
        cutoff = time.monotonic() - self.settings.board_idle_close_seconds
        for board_id, used in list(self._last_used.items()):
            if used < cutoff:
                engine = self._engines.pop(board_id, None)
                self._last_used.pop(board_id, None)
                self._verified.discard(board_id)
                self._fts.pop(board_id, None)
                if engine is not None:
                    engine.dispose()

    def _evict_overflow(self) -> None:
        if len(self._engines) <= MAX_CACHED_BOARDS:
            return
        oldest = sorted(self._last_used.items(), key=lambda item: item[1])
        for board_id, _ in oldest[: len(self._engines) - MAX_CACHED_BOARDS]:
            engine = self._engines.pop(board_id, None)
            self._last_used.pop(board_id, None)
            self._verified.discard(board_id)
            self._fts.pop(board_id, None)
            if engine is not None:
                engine.dispose()
