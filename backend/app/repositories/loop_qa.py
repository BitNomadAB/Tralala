"""A Loop's QA cycles, as the Loop summary and the Ticket rules read and change them.

``loop_id=None`` means every Loop of the board: the overview reads all Loops in one statement
instead of one per Loop.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopQaCyclesRow


class LoopQaRepository(Protocol):
    def cycles(self, loop_id: str | None) -> list[LoopQaCyclesRow]:
        """The cycles by cycle number."""
        ...

    def supersede_open(self, loop_id: str, *, now: str) -> None:
        """Every cycle still pending, ready or in progress becomes ``superseded``."""
        ...
