"""A board's labels, as the label routes and the cards that reference them use them."""

from __future__ import annotations

from typing import Final, Protocol, TypedDict

from ..db.generated.board import LabelsRow

LABEL_EDITABLE: Final = ("name", "color")
"""The columns ``LabelRepository.update`` may set: the keys of ``LabelChanges``."""


class LabelChanges(TypedDict, total=False):
    """A label edit: only the columns present are written."""

    name: str
    color: str


class LabelRepository(Protocol):
    def all(self) -> list[LabelsRow]:
        """Every label of the board, by name."""
        ...

    def get(self, label_id: str) -> LabelsRow | None: ...

    def find(self, reference: str) -> LabelsRow | None:
        """The label whose id or name is ``reference``."""
        ...

    def by_name(self, name: str) -> LabelsRow | None: ...

    def add(self, row: LabelsRow) -> None: ...

    def update(self, label_id: str, changes: LabelChanges) -> None:
        """Write ``changes`` (at least one column); a name is unique on the board."""
        ...

    def delete(self, label_id: str) -> None:
        """Delete the label; the cards that carry it lose it."""
        ...
