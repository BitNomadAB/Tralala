"""The Loop-owned Kanban columns, as ``ListService`` uses them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..db.generated.board import ListsRow


class ListRepository(Protocol):
    def get(self, list_id: str) -> ListsRow | None: ...

    def for_loop(self, loop_id: str, *, include_archived: bool) -> list[ListsRow]:
        """The Loop's lists in display order (position, then id)."""
        ...

    def positions(self, loop_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        """``(id, position)`` of the Loop's unarchived lists in display order, minus ``exclude``."""
        ...

    def add(self, row: ListsRow) -> None: ...

    def rename(self, list_id: str, name: str, *, now: str) -> None: ...

    def move(self, list_id: str, position: int, *, now: str) -> None: ...

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        """Rewrite positions only; renumbering is not an edit, so ``updated_at`` stays."""
        ...

    def archive(self, list_id: str, *, now: str) -> None: ...

    def restore(self, list_id: str, position: int, *, now: str) -> None: ...

    def delete(self, list_id: str) -> None: ...

    def active_card_counts(self, loop_id: str) -> dict[str, int]:
        """Unarchived cards of the Loop per list id; a list without one is absent."""
        ...

    def active_card_count(self, list_id: str) -> int: ...

    def planned_card_count(self, list_id: str) -> int:
        """Cards that came from the plan, archived or not: they keep a list traceable."""
        ...
