"""The board's activity log."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import ActivityLogRow


class ActivityRepository(Protocol):
    def add(self, entry: ActivityLogRow) -> None: ...
