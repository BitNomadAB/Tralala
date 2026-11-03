"""A Loop's approved plan, as the Loop's stage and summary read it.

``loop_id=None`` means every Loop of the board: the overview reads all Loops in one statement
instead of one per Loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db.generated.board import LoopPlansRow


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanTotals:
    """The planned Tickets of a Loop: one per plan item and Ticket card behind it."""

    total: int
    completed: int


class LoopPlanRepository(Protocol):
    def active(self, loop_id: str) -> LoopPlansRow | None: ...

    def active_by_loop(self) -> dict[str, LoopPlansRow]:
        """Every Loop's active plan, keyed by Loop id; a Loop without one is absent."""
        ...

    def phase_counts(self, loop_id: str | None) -> dict[str, int]:
        """Phases per Loop id; a Loop without one is absent."""
        ...

    def ticket_totals(self, loop_id: str | None) -> dict[str, PlanTotals]:
        """Planned items per Loop id, each joined to its cards; a Loop without one is absent."""
        ...
