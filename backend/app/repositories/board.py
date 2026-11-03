"""The unit of work of one board database.

A service asks for ``reader(board_id)`` or ``writer(board_id)`` and works with the repositories it
is handed until the block ends. A writer commits when the block ends normally and rolls back when
it raises; a reader never commits. The SQL implementation runs on ``BoardDatabaseManager``, so the
per-board lock, the transaction and the write notification stay where they are.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .activity import ActivityRepository
from .counters import CounterRepository
from .labels import LabelRepository
from .lists import ListRepository
from .loops import LoopRepository


class BoardRepositories(Protocol):
    """The repositories of one board, inside one reader or writer."""

    @property
    def lists(self) -> ListRepository: ...

    @property
    def loops(self) -> LoopRepository: ...

    @property
    def activity(self) -> ActivityRepository: ...

    @property
    def labels(self) -> LabelRepository: ...

    @property
    def counters(self) -> CounterRepository: ...


class BoardUnitOfWork(Protocol):
    def exists(self, board_id: str) -> bool:
        """Whether the board's database exists; it says nothing about the registry row."""
        ...

    def reader(self, board_id: str) -> AbstractContextManager[BoardRepositories]: ...

    def writer(self, board_id: str) -> AbstractContextManager[BoardRepositories]: ...
