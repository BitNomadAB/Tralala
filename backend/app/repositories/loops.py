"""Loops: the planning container that owns its Kanban, its documents, its plan and its QA."""

from __future__ import annotations

from typing import Final, Protocol, TypedDict

from ..db.generated.board import LoopsRow

LOOP_EDITABLE: Final = ("name", "goal", "version", "updated_at")
"""The columns ``LoopRepository.update`` may set: the keys of ``LoopChanges``."""


class LoopChanges(TypedDict, total=False):
    """A Loop edit: only the columns present are written."""

    name: str
    goal: str
    version: int
    updated_at: str


class LoopRepository(Protocol):
    def get(self, loop_id: str) -> LoopsRow | None:
        """The Loop, archived, cancelled and completed ones included."""
        ...

    def listing(
        self, *, include_archived: bool, include_completed: bool, stage: str | None
    ) -> list[LoopsRow]:
        """Open Loops first, then by sequence and id; ``stage`` keeps only that stage."""
        ...

    def next_sequence(self) -> int:
        """One more than the highest sequence the board has used (1 for the first Loop)."""
        ...

    def add(self, row: LoopsRow) -> None: ...

    def update(self, loop_id: str, changes: LoopChanges) -> None: ...

    def cancel(self, loop_id: str, *, now: str) -> None:
        """Stage ``cancelled``, the cancellation time, and the next version."""
        ...

    def archive(self, loop_id: str, *, now: str) -> None:
        """The archive time and the next version."""
        ...

    def set_stage(self, loop_id: str, stage: str, *, now: str) -> None:
        """A computed stage; it is not an edit, so the version stays."""
        ...

    def clear_delivery_approvals(self, loop_id: str, *, now: str) -> None:
        """Forget the implementation and QA approvals: reopened work must be accepted again."""
        ...
