"""A Ticket's checklists and their items, as ``ChecklistService`` uses them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol, TypedDict

from ..db.generated.board import ChecklistItemsRow, ChecklistsRow

CHECKLIST_ITEM_EDITABLE: Final = ("text", "completed", "position")
"""The columns ``ChecklistItemRepository.update`` may set: the keys of ``ChecklistItemChanges``."""


class ChecklistItemChanges(TypedDict, total=False):
    """A checklist item edit: only the columns present are written."""

    text: str
    completed: int
    position: int


class ChecklistRepository(Protocol):
    def get(self, checklist_id: str) -> ChecklistsRow | None: ...

    def for_card(self, card_id: str) -> list[ChecklistsRow]:
        """The card's checklists in display order (position, then id)."""
        ...

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        """Rewrite positions only."""
        ...

    def add(self, row: ChecklistsRow) -> None: ...

    def rename(self, checklist_id: str, title: str) -> None: ...

    def delete(self, checklist_id: str) -> None:
        """Delete the checklist; its items go with it."""
        ...


class ChecklistItemRepository(Protocol):
    def get(self, item_id: str) -> ChecklistItemsRow | None: ...

    def for_card(self, card_id: str) -> list[ChecklistItemsRow]:
        """The items of every checklist of the card, in display order (position, then id)."""
        ...

    def for_checklist(self, checklist_id: str) -> list[ChecklistItemsRow]:
        """The checklist's items in display order (position, then id)."""
        ...

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        """Rewrite positions only."""
        ...

    def add(self, row: ChecklistItemsRow) -> None: ...

    def update(self, item_id: str, changes: ChecklistItemChanges) -> None:
        """Write ``changes`` (at least one column)."""
        ...

    def delete(self, item_id: str) -> None: ...
