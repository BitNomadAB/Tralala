"""Ticket-bound discussions: threads, messages, participants, votes, runs, rounds and outcomes,
as ``DiscussionService``, ``RunService`` and the round engine use them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from ..db.generated.board import (
    CardsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
    LoopsRow,
)


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
        self, *, status: str | None, card_id: str | None, limit: int
    ) -> list[DiscussionThreadsRow]:
        """Threads by most recent activity, optionally in one status and on one Ticket."""
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
