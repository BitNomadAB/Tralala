"""What waits for an actor in the discussions: the ``notices`` a worker's next tool answer carries.

The server never pushes anything to a client (the MCP revision in use has no server stream), so
when something waits for an actor, the answer to its next tool call says so. A thread waits for the
actor for one reason (``reason_of``), the first that holds:

- ``comment_after_close``: the actor is involved (opened the thread or wrote in it), someone else
  wrote after the actor's read marker (or the actor has none), and the newest such message came
  after the thread was closed;
- ``answer``: the same, with the newest such message written while the thread was open;
- ``run_failed``: a run the actor started in the thread failed after its marker (or it has none),
  and nothing else is new there;
- ``open_question``: a discussion on the board (no Ticket) that is not closed, cancelled, approved
  or vetoed, the actor is not involved in and has no marker for.

A thread leaves the notices once the actor reads it (``read_discussion`` moves the marker); an
open question also once it is closed. Notices name a thread by its id, its board and its title cut
to ``TITLE_CHARS``, never with a message's text; at most ``NOTICE_THREADS`` of them, newest
activity first, with ``more`` counting the rest. The rows come from one statement per board
(``repos.reads.notices``); the reasons, the order and the cap are pure functions of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, TypedDict

from ..core.context import ActorContext
from ..core.identifiers import canonical_board_id
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.discussions import NoticeThread
from ..repositories.registry import RegistryUnitOfWork
from .discussion_inbox import each_board

NOTICE_THREADS: Final = 5
TITLE_CHARS: Final = 80
# What one board may contribute to the count; a guard, not a page size.
BOARD_NOTICE_LIMIT: Final = 1000
NEXT_STEP: Final = (
    "Read each thread with read_discussion (board_id, discussion_id); reading it takes it out "
    "of notices."
)


class NoticeEntry(TypedDict):
    discussion_id: str
    board_id: str
    title: str
    reason: str


class Notices(TypedDict):
    count: int
    threads: list[NoticeEntry]
    more: int
    next_step: str


def reason_of(entry: NoticeThread) -> str | None:
    """Why the thread waits for the actor, or ``None`` when it does not."""
    if entry.involved and entry.news:
        return "comment_after_close" if entry.news_after_closed else "answer"
    if entry.run_failed and not entry.news:
        return "run_failed"
    if (
        entry.thread.card_id is None
        and entry.thread.status not in {"closed", "cancelled", "approved", "vetoed"}
        and not entry.involved
        and not entry.marked
    ):
        return "open_question"
    return None


def short_title(title: str) -> str:
    """The title as notices give it: at most ``TITLE_CHARS`` characters."""
    return title[:TITLE_CHARS]


def collect(found: Iterable[tuple[str, Sequence[NoticeThread]]]) -> Notices | None:
    """The notices of the threads each board found, newest activity first over every board;
    ``None`` when nothing waits."""
    waiting = [
        (entry.thread.last_activity_at, board_id, entry, reason)
        for board_id, entries in found
        for entry in entries
        if (reason := reason_of(entry)) is not None
    ]
    if not waiting:
        return None
    waiting.sort(key=lambda item: (item[1], item[2].thread.id))
    waiting.sort(key=lambda item: item[0], reverse=True)
    threads: list[NoticeEntry] = [
        {
            "discussion_id": entry.thread.id,
            "board_id": board_id,
            "title": short_title(entry.thread.title),
            "reason": reason,
        }
        for _, board_id, entry, reason in waiting[:NOTICE_THREADS]
    ]
    return {
        "count": len(waiting),
        "threads": threads,
        "more": max(0, len(waiting) - NOTICE_THREADS),
        "next_step": NEXT_STEP,
    }


def read_notices(
    registry: RegistryUnitOfWork,
    store: BoardUnitOfWork,
    actor: ActorContext,
    board_id: str | None,
) -> Notices | None:
    """What waits for ``actor`` on one board, or without ``board_id`` on every board that is not
    archived, read the way the inbox reads them (``each_board``)."""

    def board_notices(repos: BoardRepositories) -> list[NoticeThread]:
        return repos.reads.notices(actor.actor_id, limit=BOARD_NOTICE_LIMIT)

    if board_id is not None:
        canonical = canonical_board_id(board_id)
        with store.reader(canonical) as repos:
            return collect([(canonical, board_notices(repos))])
    found = each_board(registry, store, board_notices)
    return collect((board.id, entries) for board, entries in found)


__all__ = [
    "NEXT_STEP",
    "NOTICE_THREADS",
    "TITLE_CHARS",
    "NoticeEntry",
    "Notices",
    "collect",
    "read_notices",
    "reason_of",
    "short_title",
]
