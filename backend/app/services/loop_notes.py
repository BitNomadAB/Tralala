"""A Loop's notes: an append-only log of what belongs to the Loop and to no single Ticket.

A person or a worker writes a note (a baseline, the gates that passed, a merge, a deploy, what is
still open); the Loop page lists them, ``read_loop`` carries the newest, and finalizing the Loop
copies every note into its history snapshot. A note is never edited or deleted, and a completed,
cancelled or archived Loop takes none (``409 loop_read_only``). The same note from the same actor
within ``NOTE_DEDUPE_SECONDS`` is a retry and answers the first one.

The service reaches the board only through the board unit of work; the clock and the id source are
arguments, so every rule runs in a unit test on the fakes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ValidationFailure
from ..db.generated.board import LoopNotesRow
from ..repositories.board import BoardUnitOfWork
from .lists import BoardChecks
from .loop_qa_cycles import log_loop_activity
from .loops import ensure_writable, require_loop

NOTE_MAX_CHARACTERS = 20_000
NOTE_DEDUPE_SECONDS = 300
NOTE_PAGE_LIMIT = 200
NOTE_PAGE_DEFAULT = 50


class NoteEntry(TypedDict):
    """A note as the API answers it."""

    id: str
    loop_id: str
    author_actor_id: str
    author_actor_type: str
    author_name: str
    content: str
    created_at: str


class NotePage(TypedDict):
    """A page of notes, oldest first, and how many the Loop holds."""

    notes: list[NoteEntry]
    count: int


def note_entry(row: LoopNotesRow) -> NoteEntry:
    return {
        "id": row.id,
        "loop_id": row.loop_id,
        "author_actor_id": row.author_actor_id,
        "author_actor_type": row.author_actor_type,
        "author_name": row.author_name,
        "content": row.content,
        "created_at": row.created_at,
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopNoteService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self._clock = clock
        self._new_id = new_id

    def _is_retry(self, earlier: LoopNotesRow) -> bool:
        written = datetime.fromisoformat(earlier.created_at.replace("Z", "+00:00"))
        return (self._clock() - written).total_seconds() < NOTE_DEDUPE_SECONDS

    def add(
        self, actor: ActorContext, board_id: str, loop_id: str, content: str
    ) -> tuple[NoteEntry, bool]:
        """The new note and False, or the same actor's identical note of a moment ago and True."""
        actor.require("loops:write")
        text = content.strip()
        if not text or len(text) > NOTE_MAX_CHARACTERS:
            raise ValidationFailure(
                f"A note holds 1 to {NOTE_MAX_CHARACTERS} characters",
                details={"argument": "content", "length": len(text)},
            )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            ensure_writable(require_loop(repos, loop_id))
            earlier = repos.notes.latest_by(loop_id, actor.actor_id, digest)
            if earlier is not None and self._is_retry(earlier):
                return note_entry(earlier), True
            now = iso_utc(self._clock())
            row = LoopNotesRow(
                id=self._new_id(),
                loop_id=loop_id,
                author_actor_id=actor.actor_id,
                author_actor_type=actor.actor_type,
                author_name=actor.actor_name or actor.actor_id,
                content=text,
                content_sha256=digest,
                created_at=now,
            )
            repos.notes.add(row)
            # The log names the note and its size, never its text: the note is stored once.
            log_loop_activity(
                repos,
                actor,
                "loop.note_added",
                loop_id,
                {"note_id": row.id, "length": len(text)},
                now,
                new_id=self._new_id,
            )
        return note_entry(row), False

    def list(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        *,
        limit: int = NOTE_PAGE_DEFAULT,
        before: str | None = None,
    ) -> NotePage:
        """The newest ``limit`` notes before the note ``before``, oldest first."""
        actor.require("loops:read")
        if not 1 <= limit <= NOTE_PAGE_LIMIT:
            raise ValidationFailure(
                f"limit is 1 to {NOTE_PAGE_LIMIT}", details={"argument": "limit", "limit": limit}
            )
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            rows = repos.notes.page(loop_id, limit=limit, before=before)
            count = repos.notes.count(loop_id)
        return {"notes": [note_entry(row) for row in rows], "count": count}


__all__ = [
    "NOTE_DEDUPE_SECONDS",
    "NOTE_MAX_CHARACTERS",
    "NOTE_PAGE_DEFAULT",
    "NOTE_PAGE_LIMIT",
    "LoopNoteService",
    "NoteEntry",
    "NotePage",
    "note_entry",
]
