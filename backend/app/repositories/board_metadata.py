"""The board database's own row and the Loop columns a new Loop starts with."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import BoardLoopDefaultsRow


class BoardMetadataRepository(Protocol):
    def claim(self, board_id: str, *, now: str) -> None:
        """Write ``board_id`` into the metadata row and set ``updated_at``: a copied or imported
        database still names the board it came from."""
        ...


class LoopDefaultsRepository(Protocol):
    def add(self, row: BoardLoopDefaultsRow) -> None:
        """The board's defaults, written once when the board is created (one row, id 1)."""
        ...
