"""The numbers a dashboard shows for a board, measured inside the board's database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class BoardCounts:
    loops: int
    lists: int
    cards: int


class CounterRepository(Protocol):
    def counts(self) -> BoardCounts:
        """Open Loops (neither archived nor completed), unarchived lists and unarchived cards."""
        ...
