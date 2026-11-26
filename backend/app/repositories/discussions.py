"""Discussions on a Ticket or on the board: threads, messages, read markers, participants, votes,
runs, rounds and outcomes, as ``DiscussionService``, ``RunService`` and the round engine use
them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from ..db.generated.board import (
    CardsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionReadsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
    LoopsRow,
)

# A thread is closed when its status is ``closed``; every other status is open.
ThreadState = Literal["open", "closed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class InboxThread:
    """A thread as the inbox reads it, with its rows side by side: the Ticket and its Loop (both
    ``None`` unless the Ticket and its Loop exist), the newest round over all its runs (whose
    synthesis is current), the newest outcome (who decided) and how many take part."""

    thread: DiscussionThreadsRow
    card: CardsRow | None
    loop: LoopsRow | None
    latest_round: DiscussionRoundsRow | None
    outcome: DiscussionOutcomesRow | None
    participant_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class NoticeThread:
    """A thread that may wait for an actor, with the facts that say why.

    ``involved``: the actor opened the thread or wrote a message in it. ``marked``: the actor has
    a read marker for it. ``news``: someone else wrote a message, not deleted, newer than the
    marker (or there is no marker); ``news_after_closed``: the newest such message came after the
    close. ``run_failed``: a run the actor started failed after the marker (or there is none)."""

    thread: DiscussionThreadsRow
    involved: bool
    marked: bool
    news: bool
    news_after_closed: bool
    run_failed: bool


class NamedVote(TypedDict):
    """A vote with the display name of the participant who cast it."""

    participant_id: str
    display_name: str | None
    position: str
    justification: str
    round_number: int
    created_at: str


class DiscussionThreadRepository(Protocol):
    def get(self, discussion_id: str) -> DiscussionThreadsRow | None: ...

    def newest(
        self,
        *,
        status: str | None,
        card_id: str | None,
        limit: int,
        board_level: bool | None = None,
        state: ThreadState | None = None,
    ) -> list[DiscussionThreadsRow]:
        """Threads by most recent activity, optionally in one status and on one Ticket.

        ``board_level`` True keeps the threads on the board itself (no Ticket), False those on a
        Ticket; ``state`` ``"open"`` keeps the threads that are not closed, ``"closed"`` the closed
        ones. ``None`` filters nothing."""
        ...

    def inbox(self, *, limit: int) -> list[InboxThread]:
        """Every thread that is not cancelled, by most recent activity, read in one statement
        with its Ticket, its Loop, its newest round, its newest outcome and its participant
        count."""
        ...

    def add(self, row: DiscussionThreadsRow) -> None: ...

    def decide(self, discussion_id: str, status: str, *, now: str) -> None:
        """Set the thread's status and mark it active now."""
        ...

    def close(self, discussion_id: str, *, actor_id: str, now: str) -> None:
        """The thread is ``closed`` by ``actor_id`` now, and marked active now."""
        ...

    def reopen(self, discussion_id: str, *, now: str) -> None:
        """The thread is ``discussing`` again, no longer closed by anyone, and marked active now."""
        ...

    def note_message(self, discussion_id: str, *, now: str) -> None:
        """Mark it active now; an ``open`` thread becomes ``discussing``."""
        ...

    def set_run_state(self, discussion_id: str, run_state: str, *, now: str) -> None: ...

    def record_round(
        self, discussion_id: str, *, status: str, tokens: int, elapsed_ms: int, now: str
    ) -> None:
        """Count one more round, add its tokens and time, and set the thread's status."""
        ...

    def settle_run_states(self) -> None:
        """A thread marked running or paused without such a run goes back to idle."""
        ...


class DiscussionMessageRepository(Protocol):
    def for_thread(self, discussion_id: str) -> list[DiscussionMessagesRow]:
        """The thread's messages that are not deleted, oldest first."""
        ...

    def newest(self, discussion_id: str, *, limit: int) -> list[DiscussionMessagesRow]:
        """The thread's latest messages that are not deleted, newest first."""
        ...

    def count(self, discussion_id: str) -> int: ...

    def agent_answers(self, discussion_id: str) -> int:
        """How many messages that are not deleted agents wrote in the thread."""
        ...

    def last_digest(self, discussion_id: str, author_actor_id: str) -> str | None:
        """The content digest of the author's latest message in the thread, if any."""
        ...

    def belongs(self, message_id: str, discussion_id: str) -> bool: ...

    def add(self, row: DiscussionMessagesRow) -> None: ...


class DiscussionReadRepository(Protocol):
    """When each actor last read each thread: what is new for a person or an API key."""

    def get(self, discussion_id: str, actor_id: str) -> DiscussionReadsRow | None: ...

    def mark(self, discussion_id: str, actor_id: str, *, now: str) -> None:
        """The actor has read the thread now: its marker is set to ``now``, made if it is new."""
        ...

    def unread_ids(self, actor_id: str, discussion_ids: Sequence[str]) -> set[str]:
        """Of ``discussion_ids``, the threads holding a message that is not deleted, that someone
        other than the actor wrote, and that is newer than the actor's marker for the thread or
        meets no marker at all."""
        ...

    def notices(self, actor_id: str, *, limit: int) -> list[NoticeThread]:
        """The threads that may wait for the actor, newest activity first, at most ``limit``, in
        one statement: one the actor is involved in that has news, one where a run the actor
        started failed after its marker, and an open question: a thread on the board (no Ticket)
        that is not closed, cancelled, approved or vetoed, the actor is not involved in and holds
        no marker for."""
        ...


class DiscussionParticipantRepository(Protocol):
    def for_thread(self, discussion_id: str) -> list[DiscussionParticipantsRow]:
        """The thread's participants in the order they joined."""
        ...

    def count(self, discussion_id: str) -> int: ...

    def add(self, row: DiscussionParticipantsRow) -> None: ...


class DiscussionVoteRepository(Protocol):
    def with_names(self, discussion_id: str) -> list[NamedVote]:
        """The thread's votes in the order they were cast, with each participant's name."""
        ...

    def latest_position(self, discussion_id: str, participant_id: str) -> str | None: ...

    def newest_first(self, discussion_id: str) -> list[DiscussionVotesRow]: ...

    def add(self, row: DiscussionVotesRow) -> None: ...


class DiscussionRunRepository(Protocol):
    def get(self, run_id: str) -> DiscussionRunsRow | None: ...

    def recent(self, discussion_id: str, *, limit: int) -> list[DiscussionRunsRow]:
        """The thread's runs, newest first."""
        ...

    def active(self, discussion_id: str) -> DiscussionRunsRow | None:
        """The thread's newest running or paused run."""
        ...

    def add(self, row: DiscussionRunsRow) -> None: ...

    def pause(self, run_id: str, reason: str | None) -> None:
        """A running run pauses with ``reason``; any other run is left as it is."""
        ...

    def resume(self, run_id: str) -> None: ...

    def end(self, run_id: str, *, status: str, reason: str | None, now: str) -> None:
        """A running run ends in ``status``; any other run is left as it is."""
        ...

    def stop(self, run_id: str, *, now: str) -> None:
        """A running or paused run stops at a person's request."""
        ...

    def fail(self, run_id: str, *, error: str, now: str) -> None:
        """A running or paused run fails with ``error``."""
        ...

    def fail_interrupted(self, *, now: str) -> int:
        """Every running or paused run fails as interrupted by a restart; how many did."""
        ...

    def record_round(self, run_id: str, *, round_number: int, elapsed_ms: int) -> None: ...

    def add_tokens(self, run_id: str, tokens: int) -> None: ...


class DiscussionRoundRepository(Protocol):
    def for_run(self, run_id: str) -> list[DiscussionRoundsRow]:
        """The run's rounds in order."""
        ...

    def last_for_run(self, run_id: str) -> DiscussionRoundsRow | None: ...

    def newest_for_thread(self, discussion_id: str) -> DiscussionRoundsRow | None:
        """The thread's latest round over all its runs, the one whose synthesis is current."""
        ...

    def add(self, row: DiscussionRoundsRow) -> None: ...


class DiscussionOutcomeRepository(Protocol):
    def newest(self, discussion_id: str) -> DiscussionOutcomesRow | None:
        """The thread's latest outcome: the decision a person recorded last."""
        ...

    def add(self, row: DiscussionOutcomesRow) -> None: ...
