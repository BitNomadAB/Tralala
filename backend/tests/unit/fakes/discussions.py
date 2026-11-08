"""In-memory discussion repositories over a ``BoardState``: the rows a test sets up and the
services change. List order stands in for SQLite's rowid order."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.generated.board import (
    CommentMentionJobsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
)
from app.repositories.discussions import InboxThread, NamedVote
from tests.unit.fakes.registry import ConstraintError

if TYPE_CHECKING:
    from tests.unit.fakes.board import BoardState

ACTIVE = ("running", "paused")


class FakeDiscussionThreadRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, discussion_id: str) -> DiscussionThreadsRow | None:
        return self._state.discussions.get(discussion_id)

    def newest(
        self, *, status: str | None, card_id: str | None, limit: int
    ) -> list[DiscussionThreadsRow]:
        rows = [
            row
            for row in self._state.discussions.values()
            if (not status or row.status == status) and (not card_id or row.card_id == card_id)
        ]
        return sorted(rows, key=lambda row: row.last_activity_at, reverse=True)[:limit]

    def inbox(self, *, limit: int) -> list[InboxThread]:
        rounds = FakeDiscussionRoundRepository(self._state)
        outcomes = FakeDiscussionOutcomeRepository(self._state)
        rows = sorted(
            (row for row in self._state.discussions.values() if row.status != "cancelled"),
            key=lambda row: row.id,
        )
        rows.sort(key=lambda row: row.last_activity_at, reverse=True)
        entries: list[InboxThread] = []
        for row in rows[:limit]:
            card = self._state.cards.get(row.card_id) if row.card_id is not None else None
            loop = (
                self._state.loops.get(card.loop_id)
                if card is not None
                else None
            )
            entries.append(
                InboxThread(
                    thread=row,
                    card=card,
                    loop=loop,
                    latest_round=rounds.newest_for_thread(row.id),
                    outcome=outcomes.newest(row.id),
                    participant_count=sum(
                        1 for p in self._state.participants if p.discussion_id == row.id
                    ),
                )
            )
        return entries

    def add(self, row: DiscussionThreadsRow) -> None:
        if row.id in self._state.discussions:
            raise ConstraintError(f"discussion_threads.id {row.id} exists")
        if row.card_id is not None and row.card_id not in self._state.cards:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.discussions[row.id] = row

    def decide(self, discussion_id: str, status: str, *, now: str) -> None:
        row = self._state.discussions.get(discussion_id)
        if row is not None:
            self._state.discussions[discussion_id] = row.__replace__(
                status=status, updated_at=now, last_activity_at=now
            )

    def note_message(self, discussion_id: str, *, now: str) -> None:
        row = self._state.discussions.get(discussion_id)
        if row is not None:
            status = "discussing" if row.status == "open" else row.status
            self._state.discussions[discussion_id] = row.__replace__(
                status=status, updated_at=now, last_activity_at=now
            )

    def set_run_state(self, discussion_id: str, run_state: str, *, now: str) -> None:
        row = self._state.discussions.get(discussion_id)
        if row is not None:
            self._state.discussions[discussion_id] = row.__replace__(
                run_state=run_state, updated_at=now
            )

    def record_round(
        self, discussion_id: str, *, status: str, tokens: int, elapsed_ms: int, now: str
    ) -> None:
        row = self._state.discussions.get(discussion_id)
        if row is not None:
            self._state.discussions[discussion_id] = row.__replace__(
                round_count=row.round_count + 1,
                status=status,
                tokens_used=row.tokens_used + tokens,
                elapsed_ms=row.elapsed_ms + elapsed_ms,
                updated_at=now,
                last_activity_at=now,
            )

    def settle_run_states(self) -> None:
        active = {run.discussion_id for run in self._state.runs.values() if run.status in ACTIVE}
        for discussion_id, row in list(self._state.discussions.items()):
            if row.run_state in ACTIVE and discussion_id not in active:
                self._state.discussions[discussion_id] = row.__replace__(run_state="idle")


class FakeDiscussionMessageRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def _live(self, discussion_id: str) -> list[DiscussionMessagesRow]:
        return [
            row
            for row in self._state.discussion_messages
            if row.discussion_id == discussion_id and row.deleted_at is None
        ]

    def for_thread(self, discussion_id: str) -> list[DiscussionMessagesRow]:
        return sorted(self._live(discussion_id), key=lambda row: row.created_at)

    def newest(self, discussion_id: str, *, limit: int) -> list[DiscussionMessagesRow]:
        return sorted(self._live(discussion_id), key=lambda row: row.created_at, reverse=True)[
            :limit
        ]

    def count(self, discussion_id: str) -> int:
        return len(self._live(discussion_id))

    def agent_answers(self, discussion_id: str) -> int:
        return sum(1 for row in self._live(discussion_id) if row.author_type == "agent")

    def last_digest(self, discussion_id: str, author_actor_id: str) -> str | None:
        mine = [
            (row.created_at, position, row)
            for position, row in enumerate(self._state.discussion_messages)
            if row.discussion_id == discussion_id
            and row.author_actor_id == author_actor_id
            and row.deleted_at is None
        ]
        if not mine:
            return None
        return max(mine, key=lambda entry: (entry[0], entry[1]))[2].content_sha256

    def belongs(self, message_id: str, discussion_id: str) -> bool:
        return any(
            row.id == message_id and row.discussion_id == discussion_id
            for row in self._state.discussion_messages
        )

    def add(self, row: DiscussionMessagesRow) -> None:
        if row.discussion_id not in self._state.discussions:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.discussion_messages.append(row)


class FakeDiscussionParticipantRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def for_thread(self, discussion_id: str) -> list[DiscussionParticipantsRow]:
        rows = [row for row in self._state.participants if row.discussion_id == discussion_id]
        return sorted(rows, key=lambda row: row.joined_at)

    def count(self, discussion_id: str) -> int:
        return len(self.for_thread(discussion_id))

    def add(self, row: DiscussionParticipantsRow) -> None:
        if row.discussion_id not in self._state.discussions:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.participants.append(row)


class FakeDiscussionVoteRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def with_names(self, discussion_id: str) -> list[NamedVote]:
        # The statement joins participants on participant_id alone, so an agent that takes part in
        # several threads answers once per participation; the fake keeps that.
        votes = [
            (row.created_at, position, row)
            for position, row in enumerate(self._state.votes)
            if row.discussion_id == discussion_id
        ]
        named: list[NamedVote] = []
        for _, _, vote in sorted(votes, key=lambda entry: (entry[0], entry[1])):
            matches = [
                p for p in self._state.participants if p.participant_id == vote.participant_id
            ]
            names: list[str | None] = [p.display_name for p in matches] or [None]
            named.extend(
                {
                    "participant_id": vote.participant_id,
                    "display_name": display_name,
                    "position": vote.position,
                    "justification": vote.justification,
                    "round_number": vote.round_number,
                    "created_at": vote.created_at,
                }
                for display_name in names
            )
        return named

    def latest_position(self, discussion_id: str, participant_id: str) -> str | None:
        mine = [
            (row.round_number, position, row.position)
            for position, row in enumerate(self._state.votes)
            if row.discussion_id == discussion_id and row.participant_id == participant_id
        ]
        return max(mine)[2] if mine else None

    def newest_first(self, discussion_id: str) -> list[DiscussionVotesRow]:
        return [row for row in reversed(self._state.votes) if row.discussion_id == discussion_id]

    def add(self, row: DiscussionVotesRow) -> None:
        if row.discussion_id not in self._state.discussions:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.votes.append(row)


class FakeDiscussionRunRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, run_id: str) -> DiscussionRunsRow | None:
        return self._state.runs.get(run_id)

    def recent(self, discussion_id: str, *, limit: int) -> list[DiscussionRunsRow]:
        rows = [row for row in self._state.runs.values() if row.discussion_id == discussion_id]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]

    def active(self, discussion_id: str) -> DiscussionRunsRow | None:
        rows = [row for row in self.recent(discussion_id, limit=1_000) if row.status in ACTIVE]
        return rows[0] if rows else None

    def add(self, row: DiscussionRunsRow) -> None:
        if row.id in self._state.runs:
            raise ConstraintError(f"discussion_runs.id {row.id} exists")
        self._state.runs[row.id] = row

    def _in(self, run_id: str, statuses: tuple[str, ...]) -> DiscussionRunsRow | None:
        row = self._state.runs.get(run_id)
        return row if row is not None and row.status in statuses else None

    def pause(self, run_id: str, reason: str | None) -> None:
        if (row := self._in(run_id, ("running",))) is not None:
            self._state.runs[run_id] = row.__replace__(status="paused", stop_reason=reason)

    def resume(self, run_id: str) -> None:
        row = self._state.runs.get(run_id)
        if row is not None:
            self._state.runs[run_id] = row.__replace__(status="running", stop_reason=None)

    def end(self, run_id: str, *, status: str, reason: str | None, now: str) -> None:
        if (row := self._in(run_id, ("running",))) is not None:
            self._state.runs[run_id] = row.__replace__(
                status=status, stop_reason=reason, finished_at=now
            )

    def stop(self, run_id: str, *, now: str) -> None:
        if (row := self._in(run_id, ACTIVE)) is not None:
            self._state.runs[run_id] = row.__replace__(
                status="stopped", stop_reason="human_stop", finished_at=now
            )

    def fail(self, run_id: str, *, error: str, now: str) -> None:
        if (row := self._in(run_id, ACTIVE)) is not None:
            self._state.runs[run_id] = row.__replace__(
                status="failed", stop_reason="error", error=error, finished_at=now
            )

    def fail_interrupted(self, *, now: str) -> int:
        failed = 0
        for run_id, row in list(self._state.runs.items()):
            if row.status in ACTIVE:
                self._state.runs[run_id] = row.__replace__(
                    status="failed",
                    stop_reason="process_restart",
                    error="process_restart",
                    finished_at=now,
                )
                failed += 1
        return failed

    def record_round(self, run_id: str, *, round_number: int, elapsed_ms: int) -> None:
        row = self._state.runs.get(run_id)
        if row is not None:
            self._state.runs[run_id] = row.__replace__(
                rounds_completed=round_number, elapsed_ms=row.elapsed_ms + elapsed_ms
            )

    def add_tokens(self, run_id: str, tokens: int) -> None:
        row = self._state.runs.get(run_id)
        if row is not None:
            self._state.runs[run_id] = row.__replace__(tokens_used=row.tokens_used + tokens)


class FakeDiscussionRoundRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def for_run(self, run_id: str) -> list[DiscussionRoundsRow]:
        rows = [row for row in self._state.rounds if row.run_id == run_id]
        return sorted(rows, key=lambda row: row.round_number)

    def last_for_run(self, run_id: str) -> DiscussionRoundsRow | None:
        rows = self.for_run(run_id)
        return rows[-1] if rows else None

    def newest_for_thread(self, discussion_id: str) -> DiscussionRoundsRow | None:
        # Ties on created_at go to the later insert, as rowid breaks them in SQLite.
        rows = [
            (row.created_at, position, row)
            for position, row in enumerate(self._state.rounds)
            if row.discussion_id == discussion_id
        ]
        return max(rows, key=lambda entry: (entry[0], entry[1]))[2] if rows else None

    def add(self, row: DiscussionRoundsRow) -> None:
        self._state.rounds.append(row)


class FakeMentionJobRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def for_card(self, card_id: str) -> list[CommentMentionJobsRow]:
        rows = [row for row in self._state.mention_jobs.values() if row.card_id == card_id]
        return sorted(rows, key=lambda row: row.created_at)

    def get(self, job_id: str) -> CommentMentionJobsRow | None:
        return self._state.mention_jobs.get(job_id)

    def add_once(self, row: CommentMentionJobsRow) -> bool:
        # uq_comment_mentions_once: one job per comment and agent.
        if any(
            job.comment_id == row.comment_id and job.agent_id == row.agent_id
            for job in self._state.mention_jobs.values()
        ):
            return False
        self._state.mention_jobs[row.id] = row
        return True

    def queued_ids(self) -> list[str]:
        rows = [row for row in self._state.mention_jobs.values() if row.status == "queued"]
        return [row.id for row in sorted(rows, key=lambda row: row.created_at)]

    def requeue(self, job_id: str) -> None:
        row = self._state.mention_jobs.get(job_id)
        if row is not None:
            self._state.mention_jobs[job_id] = row.__replace__(
                status="queued", error=None, started_at=None, finished_at=None
            )

    def start(self, job_id: str, *, now: str) -> None:
        row = self._state.mention_jobs.get(job_id)
        if row is not None:
            self._state.mention_jobs[job_id] = row.__replace__(
                status="running", attempts=row.attempts + 1, error=None, started_at=now
            )

    def complete(self, job_id: str, *, tokens: int, now: str) -> bool:
        row = self._state.mention_jobs.get(job_id)
        if row is None or row.status != "running" or row.response_comment_id is not None:
            return False
        self._state.mention_jobs[job_id] = row.__replace__(
            status="completed", tokens_used=tokens, error=None, finished_at=now
        )
        return True

    def set_response(self, job_id: str, comment_id: str) -> None:
        row = self._state.mention_jobs.get(job_id)
        if row is not None:
            self._state.mention_jobs[job_id] = row.__replace__(response_comment_id=comment_id)

    def fail(self, job_id: str, *, error: str, now: str) -> bool:
        row = self._state.mention_jobs.get(job_id)
        if row is None or row.status != "running":
            return False
        self._state.mention_jobs[job_id] = row.__replace__(
            status="failed", error=error, finished_at=now
        )
        return True

    def fail_running(self, *, now: str) -> int:
        failed = 0
        for job_id, row in list(self._state.mention_jobs.items()):
            if row.status == "running":
                self._state.mention_jobs[job_id] = row.__replace__(
                    status="failed", error="process_restart", finished_at=now
                )
                failed += 1
        return failed


class FakeDiscussionOutcomeRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def newest(self, discussion_id: str) -> DiscussionOutcomesRow | None:
        # Ties on created_at go to the later insert, as rowid breaks them in SQLite.
        rows = [
            (row.created_at, position, row)
            for position, row in enumerate(self._state.outcomes)
            if row.discussion_id == discussion_id
        ]
        return max(rows, key=lambda entry: (entry[0], entry[1]))[2] if rows else None

    def add(self, row: DiscussionOutcomesRow) -> None:
        self._state.outcomes.append(row)
