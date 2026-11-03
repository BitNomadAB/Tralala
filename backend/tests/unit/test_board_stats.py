"""BoardStatsCache's rules on an in-memory registry and board: what is measured, what is
remembered, for how long, and what a board that cannot be opened counts as.

The cache runs its real code; only the repositories, both units of work and the clock are replaced,
by the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.db.generated.registry import BoardStatsRow
from app.services.board_stats import BoardStatsCache
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import (
    FakeRegistryRepositories,
    FakeRegistryUnitOfWork,
    RegistryState,
    board_row,
)
from tests.unit.log_lines import events

NOW = datetime(2026, 11, 3, 10, 0, 0, 400_000, tzinfo=UTC)
NOW_TEXT = "2026-11-03T10:00:00Z"
MISSING = "5d0c4a1e-0000-4000-8000-000000000001"
REPAIRING = "5d0c4a1e-0000-4000-8000-000000000002"
BROKEN = "5d0c4a1e-0000-4000-8000-000000000003"
TTL = 60


@dataclass(slots=True)
class Cache:
    registry: RegistryState
    store: FakeRegistryUnitOfWork
    boards: FakeBoardUnitOfWork
    cache: BoardStatsCache


def make_cache(settings: Settings, *, ttl: int = TTL, now: datetime = NOW) -> Cache:
    """``BOARD_ID`` holds 2 open Loops, 2 open lists and 1 open card; ``MISSING`` has no database,
    ``REPAIRING`` is being migrated and SQLite cannot read ``BROKEN``'s file."""
    board = BoardState()
    board.loops = {
        "open": loop_row("open"),
        "second": loop_row("second", stage="analysis"),
        "done": loop_row("done", completed_at=CREATED),
        "old": loop_row("old", archived_at=CREATED),
    }
    rows = [
        list_row("a", "open", 1024),
        list_row("b", "open", 2048),
        list_row("c", "open", 3072, archived_at=CREATED),
    ]
    board.lists = {row.id: row for row in rows}
    board.cards = {
        "1": card_row("1", "a", "open"),
        "2": card_row("2", "a", "open", archived_at=CREATED),
    }
    boards = FakeBoardUnitOfWork(
        board,
        databases=(BOARD_ID, REPAIRING, BROKEN),
        unavailable=(REPAIRING,),
        unreadable=(BROKEN,),
    )
    registry = RegistryState()
    registry.boards = {
        board_id: board_row(board_id) for board_id in (BOARD_ID, MISSING, REPAIRING, BROKEN)
    }
    store = FakeRegistryUnitOfWork(registry)
    configured = settings.model_copy(update={"board_counts_cache_seconds": ttl})
    cache = BoardStatsCache(configured, store, boards, clock=lambda: now)
    return Cache(registry, store, boards, cache)


def stored(
    board_id: str, measured_at: str, counts: tuple[int, int, int] = (7, 8, 9)
) -> BoardStatsRow:
    loops, lists, cards = counts
    return BoardStatsRow(
        board_id=board_id,
        loop_count=loops,
        list_count=lists,
        card_count=cards,
        measured_at=measured_at,
    )


def ago(seconds: int) -> str:
    return (NOW - timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


@pytest.fixture
def cache(settings: Settings) -> Cache:
    return make_cache(settings)


def test_a_board_without_counters_is_measured_and_remembered(cache: Cache) -> None:
    assert cache.cache.counts(BOARD_ID) == (2, 2, 1)
    assert cache.registry.board_stats[BOARD_ID] == stored(BOARD_ID, NOW_TEXT, (2, 2, 1))


def test_remembered_counters_are_used_while_fresh_without_opening_the_board(
    cache: Cache,
) -> None:
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, ago(TTL - 1))
    cache.boards.databases.clear()  # opening the board now would count zeros
    assert cache.cache.counts(BOARD_ID) == (7, 8, 9)
    assert cache.store.commits == 0


@pytest.mark.parametrize(
    "measured_at", [ago(TTL), ago(TTL + 3600), "", "yesterday", "2026-11-03T09:00:00"]
)
def test_stale_or_unreadable_counters_are_measured_again(cache: Cache, measured_at: str) -> None:
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, measured_at)
    assert cache.cache.counts(BOARD_ID) == (2, 2, 1)
    assert cache.registry.board_stats[BOARD_ID].measured_at == NOW_TEXT


def test_a_time_without_a_zone_is_read_as_utc(cache: Cache) -> None:
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, "2026-11-03T09:59:30")
    assert cache.cache.counts(BOARD_ID) == (7, 8, 9)


def test_counters_exactly_as_old_as_the_lifetime_are_stale(settings: Settings) -> None:
    cache = make_cache(settings, now=NOW.replace(microsecond=0))
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, ago(TTL))
    assert cache.cache.counts(BOARD_ID) == (2, 2, 1)


@pytest.mark.parametrize("ttl", [0, -5])
def test_without_a_lifetime_nothing_is_ever_fresh(settings: Settings, ttl: int) -> None:
    cache = make_cache(settings, ttl=ttl)
    # Even counters stamped ahead of the clock (a clock set back) are measured again.
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, "2026-11-03T11:00:00Z")
    assert cache.cache.counts(BOARD_ID) == (2, 2, 1)


def test_a_board_that_cannot_be_opened_counts_zero(cache: Cache) -> None:
    zeros = (0, 0, 0)
    assert cache.cache.counts_for([MISSING, REPAIRING]) == {MISSING: zeros, REPAIRING: zeros}
    assert cache.registry.board_stats[REPAIRING] == stored(REPAIRING, NOW_TEXT, (0, 0, 0))


def _unreadable_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        line for line in events(caplog.records) if line["event"] == "board_database_unreadable"
    ]


def test_a_board_whose_file_cannot_be_read_counts_zero_and_is_logged_once(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    cache = make_cache(settings, ttl=0)  # measured on every call
    with caplog.at_level(logging.INFO, logger="tralala"):
        assert cache.cache.counts_for([BROKEN, BOARD_ID]) == {
            BROKEN: (0, 0, 0),
            BOARD_ID: (2, 2, 1),
        }
        assert cache.cache.counts(BROKEN) == (0, 0, 0)
        assert cache.cache.counts_for([REPAIRING, MISSING]) == {
            REPAIRING: (0, 0, 0),
            MISSING: (0, 0, 0),
        }
    [line] = _unreadable_lines(caplog)
    assert line == {
        "event": "board_database_unreadable",
        "board_id": BROKEN,
        "skipped": "board_counts",
    }
    assert cache.registry.boards[BROKEN].status == "active"  # the cache never changes a status


def test_a_board_that_reads_again_is_logged_again_when_it_breaks_again(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    cache = make_cache(settings, ttl=0)
    with caplog.at_level(logging.INFO, logger="tralala"):
        cache.cache.counts(BROKEN)
        cache.boards.unreadable.clear()  # restored from a backup
        assert cache.cache.counts(BROKEN) == (2, 2, 1)
        cache.boards.unreadable.add(BROKEN)
        cache.cache.counts(BROKEN)
        cache.cache.counts(BROKEN)
    assert len(_unreadable_lines(caplog)) == 2


def test_many_boards_are_answered_once_each_in_one_lookup(cache: Cache) -> None:
    cache.registry.board_stats[MISSING] = stored(MISSING, ago(5), (1, 1, 1))
    counts = cache.cache.counts_for([BOARD_ID, MISSING, BOARD_ID])
    assert counts == {BOARD_ID: (2, 2, 1), MISSING: (1, 1, 1)}
    assert list(counts) == [MISSING, BOARD_ID]
    assert cache.store.commits == 1
    assert cache.cache.counts_for([]) == {}


def test_a_write_to_the_board_drops_its_counters(cache: Cache) -> None:
    cache.registry.board_stats[BOARD_ID] = stored(BOARD_ID, NOW_TEXT)
    cache.registry.board_stats[MISSING] = stored(MISSING, NOW_TEXT)
    cache.cache.invalidate(BOARD_ID)
    assert set(cache.registry.board_stats) == {MISSING}


class UnwritableRegistry(FakeRegistryUnitOfWork):
    """Every writer fails, as a registry on a full disk would."""

    @contextmanager
    def writer(self) -> Generator[FakeRegistryRepositories]:
        if self.commits >= 0:
            raise OSError("disk full")
        yield FakeRegistryRepositories(self.state)


def test_counters_that_cannot_be_dropped_never_fail_the_write(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    cache = make_cache(settings)
    broken = BoardStatsCache(settings, UnwritableRegistry(cache.registry), cache.boards)
    with caplog.at_level(logging.WARNING, logger="tralala"):
        broken.invalidate(BOARD_ID)
    assert events(caplog.records) == [
        {"event": "board_stats_invalidate_failed", "board_id": BOARD_ID}
    ]
