"""The board's activity log."""

from __future__ import annotations

from typing import Protocol, TypedDict

from ..db.generated.board import ActivityLogRow


class ActivityQuery(TypedDict, total=False):
    """The entries a feed asks for: each key present must match exactly."""

    entity_type: str
    entity_id: str
    actor_type: str
    action: str


class ActivityRepository(Protocol):
    def add(self, entry: ActivityLogRow) -> None: ...

    def count(self, query: ActivityQuery) -> int: ...

    def page(self, query: ActivityQuery, *, limit: int, offset: int) -> list[ActivityLogRow]:
        """Newest first (by timestamp, then id), ``limit`` entries from ``offset``."""
        ...
