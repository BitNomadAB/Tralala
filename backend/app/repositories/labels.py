"""A board's labels, as the services converted so far read and add them."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LabelsRow


class LabelRepository(Protocol):
    def all(self) -> list[LabelsRow]:
        """Every label of the board, by name."""
        ...

    def add(self, row: LabelsRow) -> None: ...
