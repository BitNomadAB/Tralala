from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from ..core.config import Settings
from ..core.errors import NotFound, ServiceUnavailable
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.sqlite import utcnow

logger = logging.getLogger("tralala")

COUNTS_SQL = (
    "SELECT"
    " (SELECT COUNT(*) FROM loops WHERE archived_at IS NULL AND completed_at IS NULL) AS loops,"
    " (SELECT COUNT(*) FROM lists WHERE archived_at IS NULL) AS lists,"
    " (SELECT COUNT(*) FROM cards WHERE archived_at IS NULL) AS cards"
)

Counts = tuple[int, int, int]


class BoardStatsCache:
    """Cached dashboard counters, kept next to the board rows in the registry.

    The numbers live inside each board's database, so measuring a list of boards means opening every
    board file. They are therefore measured once and remembered, and the remembered copy is dropped
    whenever the board is written to — ``BoardDatabaseManager`` calls :meth:`invalidate` after a
    committed transaction, and after closing or deleting a board, because those paths can replace
    the file without a transaction. ``board_counts_cache_seconds`` is the backstop for a file that
    changed behind the manager's back: after that long, a stale row is measured again.

    A measurement that fails because the board's schema is being repaired returns zeros, so a broken
    board still appears in the dashboard.
    """

    def __init__(
        self, settings: Settings, registry: Registry, boards: BoardDatabaseManager
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.boards = boards
        # The manager has exactly one write choke point, so the cache attaches itself there instead
        # of asking every service to remember to invalidate.
        boards.on_write = self.invalidate

    def counts(self, board_id: str) -> Counts:
        return self.counts_for([board_id]).get(board_id, (0, 0, 0))

    def counts_for(self, board_ids: list[str]) -> dict[str, Counts]:
        wanted = list(dict.fromkeys(board_ids))
        if not wanted:
            return {}
        stored = self.registry.board_stats(wanted)
        fresh: dict[str, Counts] = {}
        missing: list[str] = []
        for board_id in wanted:
            row = stored.get(board_id)
            if row is not None and self._is_fresh(row.get("measured_at")):
                fresh[board_id] = (
                    int(row["loop_count"]),
                    int(row["list_count"]),
                    int(row["card_count"]),
                )
            else:
                missing.append(board_id)
        for board_id in missing:
            measured = self._measure(board_id)
            self.registry.store_board_stats(board_id, *measured, measured_at=utcnow())
            fresh[board_id] = measured
        return fresh

    def invalidate(self, board_id: str) -> None:
        try:
            self.registry.forget_board_stats(board_id)
        except Exception:  # noqa: BLE001 - a cache that cannot be dropped must not fail the write
            logger.warning(
                '{"event": "board_stats_invalidate_failed", "board_id": "%s"}', board_id
            )

    def _measure(self, board_id: str) -> Counts:
        try:
            with self.boards.reader(board_id) as conn:
                row = conn.execute(text(COUNTS_SQL)).one()
            return int(row[0]), int(row[1]), int(row[2])
        except (NotFound, ServiceUnavailable):
            return 0, 0, 0

    def _is_fresh(self, measured_at: object) -> bool:
        ttl = self.settings.board_counts_cache_seconds
        if ttl <= 0:
            return False
        if not measured_at:
            return False
        try:
            stamp = datetime.fromisoformat(str(measured_at))
        except ValueError:
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return (datetime.now(UTC) - stamp).total_seconds() < ttl
