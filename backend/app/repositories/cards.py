"""Tickets: the cards of a Loop's Kanban, their labels and the counts a card shows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol, TypedDict

from ..db.generated.board import CardsRow, LabelsRow, LoopPlanItemsRow

CARD_EDITABLE: Final = (
    "title",
    "description",
    "priority",
    "due_at",
    "completed_at",
    "human_confirmed_at",
    "human_confirmed_by_actor_id",
    "assignee_actor_id",
    "assignee_type",
    "assignee_name",
    "assigned_at",
    "assigned_by_actor_id",
    "version",
    "updated_at",
)
"""The columns ``CardRepository.update`` may set: the keys of ``CardChanges``."""

CARD_SORTS: Final = ("created_at", "updated_at", "due_at", "title")
"""The columns a card list may be sorted by besides its position."""

type CardSort = Literal["position", "created_at", "updated_at", "due_at", "title"]


class CardChanges(TypedDict, total=False):
    """A card edit: only the columns present are written."""

    title: str
    description: str
    priority: str
    due_at: str | None
    completed_at: str | None
    human_confirmed_at: str | None
    human_confirmed_by_actor_id: str | None
    assignee_actor_id: str | None
    assignee_type: str | None
    assignee_name: str | None
    assigned_at: str | None
    assigned_by_actor_id: str | None
    version: int
    updated_at: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CardQuery:
    """The cards of one Loop a list asks for; every field that is set narrows the result."""

    loop_id: str
    include_archived: bool = False
    list_id: str | None = None
    contains: str | None = None
    """Text in the title or the description (SQL ``LIKE``, so ``%`` and ``_`` are wildcards)."""
    label: str | None = None
    """A label's id or name."""
    priority: str | None = None
    due_before: str | None = None
    overdue_at: str | None = None
    """Open cards due before this moment."""
    completed: bool | None = None
    unassigned: bool = False
    assignee: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CardCounts:
    checklist_total: int
    checklist_completed: int
    comment_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketProgress:
    """A Loop's Tickets and QA cards: all, completed, and archived before completion."""

    total: int
    completed: int
    archived_incomplete: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BoardTicket:
    """A card with the Loop that owns it, for the board-wide Ticket list."""

    card: CardsRow
    loop_key: str
    loop_name: str
    loop_stage: str


class CardRepository(Protocol):
    def get(self, card_id: str) -> CardsRow | None: ...

    def count(self, query: CardQuery) -> int: ...

    def page(
        self, query: CardQuery, *, sort: CardSort, descending: bool, limit: int, offset: int
    ) -> list[CardsRow]:
        """``limit`` cards from ``offset``, by ``sort`` in the given direction, then by id."""
        ...

    def board_tickets(self, *, contains: str | None, limit: int) -> list[BoardTicket]:
        """Unarchived cards of open, unarchived Loops, by Loop sequence, position and id;
        ``contains`` matches the title or the Ticket key."""
        ...

    def positions(self, list_id: str, *, exclude: str | None = None) -> list[tuple[str, int]]:
        """``(id, position)`` of the list's unarchived cards in display order, minus ``exclude``."""
        ...

    def highest_position(self, list_id: str) -> int:
        """The highest position in the list, archived cards included; 0 for an empty list."""
        ...

    def renumber(self, positions: Sequence[tuple[str, int]]) -> None:
        """Rewrite positions only; renumbering is not an edit, so ``updated_at`` stays."""
        ...

    def add(self, row: CardsRow) -> None: ...

    def update(self, card_id: str, changes: CardChanges) -> None: ...

    def sync_plan_item(self, item: LoopPlanItemsRow, *, now: str) -> None:
        """The card published from ``item`` (its id, and the item as its plan item) takes the
        item's title, instructions as description, actor, mode, human texts and Phase; its version
        stays. Any other card is left alone."""
        ...

    def move(self, card_id: str, list_id: str, position: int, *, now: str) -> None:
        """The new list and position, and the next version."""
        ...

    def archive(self, card_id: str, *, now: str) -> None:
        """The archive time and the next version."""
        ...

    def restore(self, card_id: str, position: int, *, now: str) -> None:
        """Unarchived at ``position``, with the next version."""
        ...

    def confirm_human(self, card_id: str, actor_id: str, *, now: str) -> None:
        """Completed and confirmed by ``actor_id``, with the next version."""
        ...

    def completed_tickets(self, loop_id: str) -> int:
        """Completed Ticket and QA cards of the Loop, archived ones included."""
        ...

    def progress(self, loop_id: str | None) -> dict[str, TicketProgress]:
        """Ticket and QA cards per Loop id (every Loop when ``loop_id`` is None); a Loop without
        one is absent."""
        ...

    def labels(self, card_ids: Sequence[str]) -> dict[str, list[LabelsRow]]:
        """Each card's labels by name; every requested id is a key."""
        ...

    def set_labels(self, card_id: str, label_ids: Sequence[str]) -> None:
        """Replace the card's labels; a repeated id is stored once."""
        ...

    def counts(self, card_ids: Sequence[str]) -> dict[str, CardCounts]:
        """Each card's checklist items (all, completed) and comments; every requested id is a
        key."""
        ...
