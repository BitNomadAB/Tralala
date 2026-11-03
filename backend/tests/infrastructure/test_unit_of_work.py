"""The board unit of work: a writer commits or rolls back as a whole, a reader never commits."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.repositories.sql.board import SqlBoardUnitOfWork
from app.storage.board_db import BoardDatabaseManager

_INSERT = text("INSERT INTO infrastructure_probe (value) VALUES (:value)")
_COUNT = text("SELECT COUNT(*) FROM infrastructure_probe")


class WorkInterruptedError(Exception):
    pass


@pytest.fixture
def notified(boards: BoardDatabaseManager) -> Iterator[list[str]]:
    """The boards the manager announced a committed write for, during one test."""
    seen: list[str] = []
    boards.on_write = seen.append
    yield seen
    boards.on_write = None


def _rows(store: SqlBoardUnitOfWork, board_id: str) -> int:
    with store.reader(board_id) as repositories:
        return int(repositories.connection.execute(_COUNT).scalar_one())


@pytest.mark.usefixtures("probe")
def test_a_writer_that_ends_commits_and_announces_the_write(
    store: SqlBoardUnitOfWork, board_id: str, notified: list[str]
) -> None:
    with store.writer(board_id) as repositories:
        repositories.connection.execute(_INSERT, {"value": "first"})
        repositories.connection.execute(_INSERT, {"value": "second"})

    assert _rows(store, board_id) == 2
    assert notified == [board_id]


@pytest.mark.usefixtures("probe")
def test_a_writer_that_raises_leaves_nothing_behind(
    store: SqlBoardUnitOfWork, board_id: str, notified: list[str]
) -> None:
    with pytest.raises(WorkInterruptedError), store.writer(board_id) as repositories:
        repositories.connection.execute(_INSERT, {"value": "lost"})
        raise WorkInterruptedError

    assert _rows(store, board_id) == 0
    assert notified == []


@pytest.mark.usefixtures("probe")
def test_a_reader_never_commits(
    store: SqlBoardUnitOfWork, board_id: str, notified: list[str]
) -> None:
    with store.reader(board_id) as repositories:
        repositories.connection.execute(_INSERT, {"value": "discarded"})

    assert _rows(store, board_id) == 0
    assert notified == []
