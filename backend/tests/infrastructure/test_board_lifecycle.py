"""A board lets go of its file when it is closed, swept as idle or closed with the others.

A cached engine is reused without looking at the file again, so "let go" is shown the way a restore
needs it: once the board is closed, its file can be moved away and the next open notices.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.errors import NotFound
from app.storage.board_db import BoardDatabaseManager


@contextmanager
def moved_away(path: Path) -> Iterator[None]:
    """The board file elsewhere for a moment; on Windows a held handle makes the move fail."""
    aside = path.with_name("board.sqlite.aside")
    path.replace(aside)
    try:
        yield
    finally:
        aside.replace(path)


def _use(manager: BoardDatabaseManager, board_id: str) -> None:
    with manager.reader(board_id) as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


@pytest.mark.parametrize(
    "release",
    [
        pytest.param(lambda manager, board_id: manager.close(board_id), id="close"),
        pytest.param(lambda manager, _board_id: manager.close_all(), id="close_all"),
    ],
)
def test_a_closed_board_holds_no_file(
    boards: BoardDatabaseManager,
    board_id: str,
    release: Callable[[BoardDatabaseManager, str], None],
) -> None:
    _use(boards, board_id)
    path = boards.path(board_id)

    release(boards, board_id)

    assert not path.with_name("board.sqlite-wal").exists()
    with moved_away(path), pytest.raises(NotFound, match="Board database not found"):
        boards.open(board_id)
    _use(boards, board_id)


def test_the_idle_sweep_releases_a_board_nobody_uses(settings: Settings, board_id: str) -> None:
    # A negative idle time makes every board idle the moment the sweep runs, without waiting.
    manager = BoardDatabaseManager(settings.model_copy(update={"board_idle_close_seconds": -1}))
    try:
        _use(manager, board_id)
        with moved_away(manager.path(board_id)), pytest.raises(NotFound):
            manager.open(board_id)
    finally:
        manager.close_all()


def test_without_a_sweep_an_open_board_is_reused(
    boards: BoardDatabaseManager, board_id: str
) -> None:
    """The control for the tests above: an engine that is not released is not looked up again."""
    _use(boards, board_id)
    with moved_away(boards.path(board_id)):
        assert boards.open(board_id) is boards.open(board_id)
