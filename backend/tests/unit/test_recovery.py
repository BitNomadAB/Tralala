"""Startup recovery over plain functions: every board is visited, and one board that cannot be read,
is mid-repair or has no database never stops the others or the start."""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass, field

import pytest

from app.core.errors import BoardUnreadable, NotFound, ServiceUnavailable
from app.services.recovery import recover_async_work
from tests.unit.log_lines import events

FIRST = "6a1b0000-0000-4000-8000-000000000001"
BROKEN = "6a1b0000-0000-4000-8000-000000000002"
REPAIRING = "6a1b0000-0000-4000-8000-000000000003"
MISSING = "6a1b0000-0000-4000-8000-000000000004"
LAST = "6a1b0000-0000-4000-8000-000000000005"


@dataclass(slots=True)
class Recoverer:
    """One kind of interrupted work: resolves ``found`` items on a readable board."""

    name: str
    found: int
    calls: list[tuple[str, str]]
    broken: Collection[str] = field(default_factory=tuple[str, ...])

    def __call__(self, board_id: str) -> int:
        self.calls.append((self.name, board_id))
        if board_id in self.broken:
            raise BoardUnreadable("Board database cannot be read")
        if board_id == REPAIRING:
            raise ServiceUnavailable("Board schema is not at the current revision")
        if board_id == MISSING:
            raise NotFound("Board database not found")
        return self.found


def _events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return events(caplog.records)


def test_every_recoverer_runs_on_every_board_and_the_total_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[str, str]] = []
    runs, mentions = Recoverer("runs", 1, calls), Recoverer("mentions", 2, calls)
    with caplog.at_level(logging.INFO, logger="tralala"):
        assert recover_async_work([FIRST, LAST], (runs, mentions)) == 6
    assert calls == [("runs", FIRST), ("mentions", FIRST), ("runs", LAST), ("mentions", LAST)]
    assert _events(caplog) == [{"event": "async_work_recovered", "items": 6}]


def test_a_board_whose_file_cannot_be_read_is_skipped_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[str, str]] = []
    runs = Recoverer("runs", 1, calls, broken=(BROKEN,))
    mentions = Recoverer("mentions", 0, calls, broken=(BROKEN,))
    with caplog.at_level(logging.INFO, logger="tralala"):
        assert recover_async_work([FIRST, BROKEN, LAST], (runs, mentions)) == 2
    # The broken board stops at its first recoverer; the board after it is still recovered.
    assert calls == [
        ("runs", FIRST),
        ("mentions", FIRST),
        ("runs", BROKEN),
        ("runs", LAST),
        ("mentions", LAST),
    ]
    skipped = {"event": "board_database_unreadable", "board_id": BROKEN}
    assert _events(caplog) == [
        {**skipped, "skipped": "async_work_recovery"},
        {"event": "async_work_recovered", "items": 2},
    ]


def test_what_one_recoverer_resolved_before_a_board_broke_still_counts() -> None:
    calls: list[tuple[str, str]] = []
    runs = Recoverer("runs", 3, calls)
    mentions = Recoverer("mentions", 1, calls, broken=(BROKEN,))
    assert recover_async_work([BROKEN], (runs, mentions)) == 3


def test_a_board_mid_repair_or_without_its_database_is_skipped_quietly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[str, str]] = []
    runs = Recoverer("runs", 0, calls)
    with caplog.at_level(logging.INFO, logger="tralala"):
        assert recover_async_work([REPAIRING, MISSING, LAST], (runs,)) == 0
    assert calls == [("runs", REPAIRING), ("runs", MISSING), ("runs", LAST)]
    # Both were logged where they were found (the Migration Manager, the missing-file event).
    assert caplog.records == []


def test_any_other_error_is_not_swallowed() -> None:
    def failing(board_id: str) -> int:
        raise RuntimeError(f"a bug while recovering {board_id}")

    with pytest.raises(RuntimeError, match="a bug while recovering"):
        recover_async_work([FIRST], (failing,))
