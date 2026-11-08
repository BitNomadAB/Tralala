"""A Loop's structured plans and their projections: Phases, plan items and dependencies.

The plan revision is authoritative; ``loop_phases``, ``loop_plan_items`` and ``loop_dependencies``
are its validated projections, keyed by the identities the plan carries across revisions.

``loop_id=None`` means every Loop of the board: the overview reads all Loops in one statement
instead of one per Loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db.generated.board import (
    LoopDependenciesRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanTotals:
    """The planned Tickets of a Loop: one per plan item and Ticket card behind it."""

    total: int
    completed: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedItem:
    """A plan item and the card published from it; the card fields are None (and the card's wait
    and workplace their defaults) before then."""

    item: LoopPlanItemsRow
    card_id: str | None
    completed_at: str | None
    waiting_for: str = "nothing"
    workplace: str = "unknown"


class LoopPlanRepository(Protocol):
    def get(self, plan_id: str) -> LoopPlansRow | None: ...

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

    def next_revision(self, loop_id: str) -> int:
        """One more than the Loop's highest plan revision (1 for its first plan)."""
        ...

    def add(self, row: LoopPlansRow) -> None: ...

    def attach_revisions(
        self, plan_id: str, *, roadmap_ai_revision_id: str, roadmap_revision_id: str
    ) -> None:
        """The two RoadMap revisions the plan was written to."""
        ...

    def activate(self, loop_id: str, plan_id: str, *, approval_id: str | None, now: str) -> None:
        """The Loop's other active plan is superseded at ``now``; then ``plan_id`` is the active
        one under ``approval_id``, activated at ``now`` unless it was activated before."""
        ...


class LoopPhaseRepository(Protocol):
    def get(self, loop_id: str, phase_id: str) -> LoopPhasesRow | None:
        """The Loop's Phase; a Phase of another Loop is None."""
        ...

    def for_loop(self, loop_id: str) -> list[LoopPhasesRow]:
        """Every Phase a plan of the Loop registered, by number."""
        ...

    def add(self, row: LoopPhasesRow) -> None: ...

    def update(self, row: LoopPhasesRow) -> None:
        """The Phase's plan, number, name, objective and conditions; the rest stays."""
        ...


class LoopPlanItemRepository(Protocol):
    def get(self, loop_id: str, item_id: str) -> LoopPlanItemsRow | None:
        """The Loop's plan item; an item of another Loop is None."""
        ...

    def next_sequence(self, loop_id: str, phase_number: int) -> int:
        """One more than the highest Ticket sequence of the Loop's Phase number (1 for the
        first)."""
        ...

    def add(self, row: LoopPlanItemsRow) -> None: ...

    def update(self, row: LoopPlanItemsRow) -> None:
        """The item's plan, Phase, texts, actor, mode, priority and criteria; its key, sequence
        and creation time stay."""
        ...

    def with_cards(self, loop_id: str) -> list[PlannedItem]:
        """The Loop's items by Phase number, Ticket sequence and key, each joined to the cards
        published from it: one entry per card, and one without a card when there is none."""
        ...

    def approved_faces(self, limit: int) -> list[LoopPlanItemsRow]:
        """At most ``limit`` items of any Loop of the board that carry a face (``face`` is not
        empty) and whose stored text is that of an approved RoadMap: the item's plan was published
        under an approval. Newest approval first, then in plan order (Phase number, Ticket
        sequence, key). A RoadMap run shows them as examples of a face."""
        ...


class LoopDependencyRepository(Protocol):
    def for_loop(self, loop_id: str) -> list[LoopDependenciesRow]:
        """The Loop's edges in the order they were added."""
        ...

    def clear(self, loop_id: str) -> None: ...

    def add(self, row: LoopDependenciesRow) -> None:
        """An edge the plan already has (same source and target) is kept once."""
        ...
