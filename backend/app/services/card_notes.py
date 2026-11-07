"""A person's notes on a Ticket: their own words beside the plan, never an agent's.

A person adds a note to a Ticket; the Ticket view shows it with its author and time, and
``read_ticket`` hands every note to a coding agent as ``person_notes``, a field of its own, so the
person's words reach the session that works the Ticket without being mistaken for the plan.

The rights: anyone who may read the board lists a Ticket's notes (``cards:read``); a person with
``cards:write`` adds one, and a token never does (``403 human_action_required``, AGENTS.md rule
11a's reasoning: the note is the person's word); only its author edits or deletes it
(``403 note_author_only``), an edit names the version it read (``409 version_conflict``). A note is
content, not conversation, so it follows the Ticket's description and not its comments: a
completed, cancelled or archived Loop refuses every write (``409 loop_read_only``, rule 11b), and
so does an archived board. A Loop that does not own the Ticket is ``409 loop_mismatch``.

Every write adds an activity entry on the card (the note's id and size, never its text) and a card
event in the same transaction, published once it commits, so an open Ticket view refreshes. The
service reaches the board only through the board unit of work; the clock and the id source are
arguments, so every rule runs in a unit test on the fakes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Forbidden, NotFound, VersionConflict
from ..db.generated.board import CardNotesRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.card_notes import CardNoteCreate, CardNoteUpdate
from .activity import activity_entry
from .cards_writes import ticket_in_loop
from .events import Event
from .lists import BoardChecks
from .loops_rules import ensure_writable, require_loop

# The card events a note write records; the live Ticket view refetches on them.
NOTE_ADDED = "note_added"
NOTE_EDITED = "note_edited"
NOTE_DELETED = "note_deleted"
NOTE_EVENT_TYPES = (NOTE_ADDED, NOTE_EDITED, NOTE_DELETED)


class CardNoteEntry(TypedDict):
    """A note as the API answers it."""

    id: str
    card_id: str
    author: str
    author_actor_id: str
    written_at: str
    updated_at: str
    text: str
    version: int


class CardEvents(Protocol):
    """What the service needs from ``EventService``: record in the transaction, publish after."""

    def record_card(
        self,
        repos: BoardRepositories,
        *,
        card_id: str,
        type: str,
        payload: Mapping[str, object] | None = None,
        actor: ActorContext | None = None,
    ) -> Event: ...

    def publish(self, board_id: str, event: Event) -> None: ...


def note_entry(row: CardNotesRow) -> CardNoteEntry:
    return {
        "id": row.id,
        "card_id": row.card_id,
        "author": row.author_name,
        "author_actor_id": row.author_actor_id,
        "written_at": row.created_at,
        "updated_at": row.updated_at,
        "text": row.text,
        "version": row.version,
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class CardNoteService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        events: CardEvents,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.events = events
        self._clock = clock
        self._new_id = new_id

    # --- reading -----------------------------------------------------------------------------

    def list(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str
    ) -> list[CardNoteEntry]:
        """The Ticket's notes, oldest first."""
        actor.require("cards:read")
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            ticket_in_loop(repos, loop_id, card_id)
            rows = repos.card_notes.for_card(card_id)
        return [note_entry(row) for row in rows]

    # --- writing -----------------------------------------------------------------------------

    def add(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: CardNoteCreate,
    ) -> CardNoteEntry:
        self._require_person(actor, "Writing a note on a Ticket")
        self.boards.ensure_active(board_id)
        now = iso_utc(self._clock())
        row = CardNotesRow(
            id=self._new_id(),
            card_id=card_id,
            author_actor_id=actor.actor_id,
            author_name=actor.actor_name or actor.actor_id,
            text=payload.text,
            created_at=now,
            updated_at=now,
            version=1,
        )
        with self.store.writer(board_id) as repos:
            self._ensure_writable(repos, loop_id, card_id)
            repos.card_notes.add(row)
            event = self._record(repos, actor, row, NOTE_ADDED, now)
        self.events.publish(board_id, event)
        return note_entry(row)

    def edit(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        note_id: str,
        payload: CardNoteUpdate,
    ) -> CardNoteEntry:
        self._require_person(actor, "Editing a note on a Ticket")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            self._ensure_writable(repos, loop_id, card_id)
            note = self._own_note(repos, actor, card_id, note_id)
            if note.version != payload.version:
                raise VersionConflict(
                    "The note was changed since it was read",
                    details={"expected_version": payload.version, "current_version": note.version},
                )
            now = iso_utc(self._clock())
            edited = note.__replace__(text=payload.text, updated_at=now, version=note.version + 1)
            repos.card_notes.update(
                note_id, {"text": edited.text, "updated_at": now, "version": edited.version}
            )
            event = self._record(repos, actor, edited, NOTE_EDITED, now)
        self.events.publish(board_id, event)
        return note_entry(edited)

    def delete(
        self, actor: ActorContext, board_id: str, loop_id: str, card_id: str, note_id: str
    ) -> None:
        self._require_person(actor, "Deleting a note on a Ticket")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            self._ensure_writable(repos, loop_id, card_id)
            note = self._own_note(repos, actor, card_id, note_id)
            repos.card_notes.delete(note_id)
            now = iso_utc(self._clock())
            event = self._record(repos, actor, note, NOTE_DELETED, now)
        self.events.publish(board_id, event)

    # --- rules -------------------------------------------------------------------------------

    @staticmethod
    def _require_person(actor: ActorContext, action: str) -> None:
        """A token never writes a note, whatever its scopes; a person needs ``cards:write``."""
        actor.require_human(action)
        actor.require("cards:write")

    @staticmethod
    def _ensure_writable(repos: BoardRepositories, loop_id: str, card_id: str) -> None:
        """The Loop owns the Ticket (``409 loop_mismatch``) and still takes writes."""
        ticket_in_loop(repos, loop_id, card_id)
        ensure_writable(require_loop(repos, loop_id))

    @staticmethod
    def _own_note(
        repos: BoardRepositories, actor: ActorContext, card_id: str, note_id: str
    ) -> CardNotesRow:
        """The Ticket's note, which only its author changes."""
        note = repos.card_notes.get(note_id)
        if note is None or note.card_id != card_id:
            raise NotFound("Note not found", code="note_not_found")
        if note.author_actor_id != actor.actor_id:
            raise Forbidden(
                "Only the person who wrote a note may change it",
                code="note_author_only",
                details={"note_id": note_id},
            )
        return note

    def _record(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        note: CardNotesRow,
        event_type: str,
        now: str,
    ) -> Event:
        """The activity entry on the card (the note's id, version and size, never its text) and
        the card event, both in the write's transaction."""
        changes = {"note_id": note.id, "version": note.version, "length": len(note.text)}
        repos.activity.add(
            activity_entry(
                actor,
                action=f"card.{event_type}",
                entity_type="card",
                entity_id=note.card_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=now,
            )
        )
        return self.events.record_card(
            repos,
            card_id=note.card_id,
            type=event_type,
            payload={"note_id": note.id, "version": note.version},
            actor=actor,
        )


__all__ = [
    "NOTE_ADDED",
    "NOTE_DELETED",
    "NOTE_EDITED",
    "NOTE_EVENT_TYPES",
    "CardEvents",
    "CardNoteEntry",
    "CardNoteService",
    "note_entry",
]
