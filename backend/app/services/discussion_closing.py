"""Closing a discussion and opening it again.

The one who opened a thread closes it when they have their answer; nobody else may, not even a
signed-in person. The opener, or a signed-in person, may open it again. A closed thread keeps every
word and still takes comments (``DiscussionService.add_message`` marks each ``after_closed``), but
never starts a round. A thread on a Ticket follows its Loop: a read-only Loop refuses both.

The rules are pure functions of the actor and the thread; ``close_thread`` and ``reopen_thread``
take the open repositories, write the change, its activity entry and its event, and return the
event to publish once the write is committed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..core.errors import Conflict, Forbidden, NotFound
from ..db.generated.board import DiscussionThreadsRow
from ..repositories.board import BoardRepositories
from .activity import discussion_activity
from .events import STATUS_CHANGED, Event, EventService
from .loops import ensure_ticket_writable

CLOSED = "closed"
# What a closed thread becomes again: a thread people are talking in.
REOPENED = "discussing"


def is_opener(actor: ActorContext, thread: DiscussionThreadsRow) -> bool:
    return actor.actor_id == thread.created_by_actor_id


def ensure_may_close(actor: ActorContext, thread: DiscussionThreadsRow) -> None:
    """Only the opener closes, a person or a key alike (``403 not_opener``); a thread already
    closed, or cancelled, cannot be closed (``409``)."""
    if not is_opener(actor, thread):
        raise Forbidden(
            "Only the one who opened the discussion can close it",
            code="not_opener",
            details={"discussion_id": thread.id},
        )
    if thread.status in {CLOSED, "cancelled"}:
        raise Conflict("Discussion is already closed", details={"status": thread.status})


def ensure_may_reopen(actor: ActorContext, thread: DiscussionThreadsRow) -> None:
    """The opener or a signed-in person opens a closed thread again; another key may not
    (``403 not_opener``). Only a closed thread can be opened again (``409``)."""
    if not (is_opener(actor, thread) or actor.is_user):
        raise Forbidden(
            "Only the one who opened the discussion, or a person, can open it again",
            code="not_opener",
            details={"discussion_id": thread.id},
        )
    if thread.status != CLOSED:
        raise Conflict("Discussion is not closed", details={"status": thread.status})


def _thread(repos: BoardRepositories, discussion_id: str) -> DiscussionThreadsRow:
    thread = repos.threads.get(discussion_id)
    if thread is None:
        raise NotFound("Discussion not found")
    if thread.card_id is not None:
        ensure_ticket_writable(repos, thread.card_id)
    return thread


def _record(
    events: EventService | None,
    repos: BoardRepositories,
    discussion_id: str,
    payload: Mapping[str, object],
    actor: ActorContext,
) -> Event | None:
    if events is None:
        return None
    return events.record(
        repos, discussion_id=discussion_id, type=STATUS_CHANGED, payload=payload, actor=actor
    )


def close_thread(
    repos: BoardRepositories,
    actor: ActorContext,
    discussion_id: str,
    *,
    now: str,
    new_id: Callable[[], str],
    events: EventService | None,
) -> Event | None:
    """The opener closes the thread: refused while a run is active (``409``), as a review is."""
    thread = _thread(repos, discussion_id)
    ensure_may_close(actor, thread)
    if repos.runs.active(discussion_id) is not None:
        raise Conflict("A run is still active; stop it before closing the discussion")
    repos.threads.close(discussion_id, actor_id=actor.actor_id, now=now)
    repos.activity.add(
        discussion_activity(
            actor,
            action="discussion.closed",
            card_id=thread.card_id,
            discussion_id=discussion_id,
            changes={"discussion_id": discussion_id, "status": CLOSED},
            entry_id=new_id(),
            timestamp=now,
        )
    )
    return _record(
        events,
        repos,
        discussion_id,
        {
            "status": CLOSED,
            "run_state": thread.run_state or "idle",
            "closed_at": now,
            "closed_by_actor_id": actor.actor_id,
        },
        actor,
    )


def reopen_thread(
    repos: BoardRepositories,
    actor: ActorContext,
    discussion_id: str,
    *,
    now: str,
    new_id: Callable[[], str],
    events: EventService | None,
) -> Event | None:
    """The thread is open again: ``discussing``, closed by nobody."""
    thread = _thread(repos, discussion_id)
    ensure_may_reopen(actor, thread)
    repos.threads.reopen(discussion_id, now=now)
    repos.activity.add(
        discussion_activity(
            actor,
            action="discussion.reopened",
            card_id=thread.card_id,
            discussion_id=discussion_id,
            changes={"discussion_id": discussion_id, "status": REOPENED},
            entry_id=new_id(),
            timestamp=now,
        )
    )
    return _record(
        events,
        repos,
        discussion_id,
        {"status": REOPENED, "run_state": thread.run_state or "idle", "closed_at": None},
        actor,
    )


__all__ = [
    "CLOSED",
    "REOPENED",
    "close_thread",
    "ensure_may_close",
    "ensure_may_reopen",
    "is_opener",
    "reopen_thread",
]
