"""Loops: the planning container that owns its Kanban, its documents, its plan and its QA."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, Protocol, TypedDict

from ..db.generated.board import LoopsRow

LOOP_EDITABLE: Final = ("name", "goal", "version", "updated_at")
"""The columns ``LoopRepository.update`` may set: the keys of ``LoopChanges``."""

type ApprovalColumn = Literal[
    "analysis_approval_id", "roadmap_approval_id", "implementation_approval_id", "qa_approval_id"
]

LOOP_APPROVAL_COLUMNS: Final[tuple[ApprovalColumn, ...]] = (
    "analysis_approval_id",
    "roadmap_approval_id",
    "implementation_approval_id",
    "qa_approval_id",
)
"""A Loop's approvals, upstream first: changing an input invalidates its approval and every one
after it."""


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

    def complete(self, loop_id: str, *, history_id: str, now: str) -> None:
        """Stage ``completed`` with its time and history record, and the next version."""
        ...

    def cancel(self, loop_id: str, *, now: str) -> None:
        """Stage ``cancelled``, the cancellation time, and the next version."""
        ...

    def archive(self, loop_id: str, *, now: str) -> None:
        """The archive time and the next version."""
        ...

    def set_stage(self, loop_id: str, stage: str, *, now: str) -> None:
        """A computed stage; it is not an edit, so the version stays."""
        ...

    def set_current_plan(self, loop_id: str, plan_id: str | None, *, now: str) -> None:
        """The plan the Loop now executes, or none once its plan is withdrawn; publishing is not
        an edit, so the version stays."""
        ...

    def clear_delivery_approvals(self, loop_id: str, *, now: str) -> None:
        """Forget the implementation and QA approvals: reopened work must be accepted again."""
        ...

    def clear_approvals(
        self, loop_id: str, columns: Sequence[ApprovalColumn], *, now: str
    ) -> None:
        """Forget the named approvals; it is not an edit, so the version stays."""
        ...

    def set_approval(
        self, loop_id: str, column: ApprovalColumn, approval_id: str, *, now: str
    ) -> None:
        """A review scope's approval, and the next version."""
        ...

    def accept_delivery(
        self, loop_id: str, *, implementation_approval_id: str, qa_approval_id: str, now: str
    ) -> None:
        """Implementation and an external QA accepted at once, and the next version."""
        ...

    def start_qa(
        self, loop_id: str, *, implementation_approval_id: str, cycle_id: str, now: str
    ) -> None:
        """Implementation accepted and its QA cycle active, and the next version."""
        ...

    def set_active_qa_cycle(self, loop_id: str, cycle_id: str, *, now: str) -> None:
        """The Loop's active QA cycle; it is not an edit, so the version stays."""
        ...

    def bump_version(self, loop_id: str, *, now: str) -> None:
        """The next version, as a person's decision about the Loop's documents makes it."""
        ...
