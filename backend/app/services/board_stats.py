"""Cached dashboard counters, kept next to the board rows in the registry.

The cache reaches the registry through the registry unit of work and each board through the board
unit of work (``app/repositories``); the clock is passed in, so freshness is decided in a unit test
without a database or a wait.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from ..core.config import Settings
from ..core.dates import iso_utc
from ..core.errors import NotFound, ServiceUnavailable
from ..db.generated.registry import BoardStatsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork

logger = logging.getLogger("tralala")

type Counts = tuple[int, int, int]
"""Open Loops, unarchived lists and unarchived cards, in that order."""


def _now() -> datetime:
    return datetime.now(UTC)


class BoardStatsCache:
    """Cached dashboard counters, kept next to the board rows in the registry.

    The numbers live inside each board's database, so measuring a list of boards means opening every
    board file. They are therefore measured once and remembered, and the remembered copy is dropped
    whenever the board is written to: the composition root attaches :meth:`invalidate` to
    ``BoardDatabaseManager.on_write``, which runs after a committed transaction and after a board is
    closed or deleted, because those paths can replace the file without a transaction.
    ``board_counts_cache_seconds`` is the backstop for a file that changed behind the manager's
    back: after that long, a stale row is measured again.

    A measurement that fails because the board's schema is being repaired returns zeros, so a broken
    board still appears in the dashboard.
    """

    def __init__(
        self,
        settings: Settings,
        store: RegistryUnitOfWork,
        boards: BoardUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.settings = settings
        self.store = store
        self.boards = boards
        self._clock = clock

    def counts(self, board_id: str) -> Counts:
        return self.counts_for([board_id]).get(board_id, (0, 0, 0))

    def counts_for(self, board_ids: list[str]) -> dict[str, Counts]:
        wanted = list(dict.fromkeys(board_ids))
        if not wanted:
            return {}
        with self.store.reader() as repos:
            stored = repos.board_stats.for_boards(wanted)
        fresh: dict[str, Counts] = {}
        missing: list[str] = []
        for board_id in wanted:
            row = stored.get(board_id)
            if row is not None and self._is_fresh(row.measured_at):
                fresh[board_id] = (row.loop_count, row.list_count, row.card_count)
            else:
                missing.append(board_id)
        for board_id in missing:
            measured = self._measure(board_id)
            loops, lists, cards = measured
            row = BoardStatsRow(
                board_id=board_id,
                loop_count=loops,
                list_count=lists,
                card_count=cards,
                measured_at=iso_utc(self._clock()),
            )
            with self.store.writer() as repos:
                repos.board_stats.store(row)
            fresh[board_id] = measured
        return fresh

    def invalidate(self, board_id: str) -> None:
        try:
            with self.store.writer() as repos:
                repos.board_stats.forget(board_id)
        except Exception:  # noqa: BLE001 - a cache that cannot be dropped must not fail the write
            logger.warning(
                '{"event": "board_stats_invalidate_failed", "board_id": "%s"}', board_id
            )

    def _measure(self, board_id: str) -> Counts:
        try:
            with self.boards.reader(board_id) as repos:
                counts = repos.counters.counts()
        except (NotFound, ServiceUnavailable):
            return 0, 0, 0
        return counts.loops, counts.lists, counts.cards

    def _is_fresh(self, measured_at: str) -> bool:
        ttl = self.settings.board_counts_cache_seconds
        if ttl <= 0:
            return False
        if not measured_at:
            return False
        try:
            stamp = datetime.fromisoformat(measured_at)
        except ValueError:
            return False
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return (self._clock() - stamp).total_seconds() < ttl
