"""Loops, as the services converted so far read them."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopsRow


class LoopRepository(Protocol):
    def get(self, loop_id: str) -> LoopsRow | None:
        """The Loop, archived, cancelled and completed ones included."""
        ...
