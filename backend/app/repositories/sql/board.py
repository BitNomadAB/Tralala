"""The board unit of work on ``BoardDatabaseManager``."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.engine import Connection

from ...storage.board_db import BoardDatabaseManager
from ..activity import ActivityRepository
from ..board import BoardUnitOfWork
from ..lists import ListRepository
from ..loops import LoopRepository
from .activity import SqlActivityRepository
from .lists import SqlListRepository
from .loops import SqlLoopRepository


class SqlBoardRepositories:
    """The board repositories over one connection, inside one reader or writer."""

    def __init__(self, connection: Connection) -> None:
        # Code that is not converted yet takes a Connection; this is the same transaction.
        self.connection = connection
        self.lists: ListRepository = SqlListRepository(connection)
        self.loops: LoopRepository = SqlLoopRepository(connection)
        self.activity: ActivityRepository = SqlActivityRepository(connection)


class SqlBoardUnitOfWork(BoardUnitOfWork):
    """Subclasses the Protocol so pyright checks every method against it here (PEP 544)."""

    def __init__(self, boards: BoardDatabaseManager) -> None:
        self._boards = boards

    def exists(self, board_id: str) -> bool:
        return self._boards.exists(board_id)

    @contextmanager
    def reader(self, board_id: str) -> Generator[SqlBoardRepositories]:
        with self._boards.reader(board_id) as connection:
            yield SqlBoardRepositories(connection)

    @contextmanager
    def writer(self, board_id: str) -> Generator[SqlBoardRepositories]:
        with self._boards.session(board_id) as connection:
            yield SqlBoardRepositories(connection)
