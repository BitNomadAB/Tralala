"""Discussion and ticket events, as ``EventService`` records and replays them."""

from __future__ import annotations

from typing import Protocol, TypedDict

from ..db.generated.board import CardEventsRow, DiscussionEventsRow


class NewEvent(TypedDict):
    """An event before the database numbers it: ``seq`` is assigned on insert."""

    id: str
    type: str
    payload_json: str
    actor_id: str | None
    actor_type: str | None
    actor_name: str | None
    created_at: str


class EventRepository(Protocol):
    def add_discussion_event(self, discussion_id: str, event: NewEvent) -> int:
        """Insert the event into the thread's log and return its sequence number."""
        ...

    def add_card_event(self, card_id: str, event: NewEvent) -> int:
        """Insert the event into the ticket's log and return its sequence number."""
        ...

    def discussion_events(
        self, discussion_id: str, *, after: int, limit: int
    ) -> list[DiscussionEventsRow]:
        """The thread's events with a sequence number above ``after``, oldest first."""
        ...

    def card_events(self, card_id: str, *, after: int, limit: int) -> list[CardEventsRow]:
        """The ticket's events with a sequence number above ``after``, oldest first."""
        ...

    def discussion_exists(self, discussion_id: str) -> bool: ...
