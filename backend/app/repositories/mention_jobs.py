"""Agent mention jobs on ticket comments, as ``MentionService`` queues, runs and answers them.

A job's status is its channel: queued, running, then completed or failed. Each guarded transition
answers whether it happened, so a retry or a second worker can never answer a mention twice.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import CommentMentionJobsRow


class MentionJobRepository(Protocol):
    def for_card(self, card_id: str) -> list[CommentMentionJobsRow]:
        """The ticket's jobs, oldest first."""
        ...

    def get(self, job_id: str) -> CommentMentionJobsRow | None: ...

    def add_once(self, row: CommentMentionJobsRow) -> bool:
        """Queue the job unless the comment already has one for that agent; whether it was added."""
        ...

    def queued_ids(self) -> list[str]:
        """Every queued job, oldest first."""
        ...

    def requeue(self, job_id: str) -> None:
        """Back to queued, with its error and times cleared."""
        ...

    def start(self, job_id: str, *, now: str) -> None:
        """Running, one more attempt, error cleared."""
        ...

    def complete(self, job_id: str, *, tokens: int, now: str) -> bool:
        """A running job without an answer completes; whether it did."""
        ...

    def set_response(self, job_id: str, comment_id: str) -> None: ...

    def fail(self, job_id: str, *, error: str, now: str) -> bool:
        """A running job fails with ``error``; whether it did."""
        ...

    def fail_running(self, *, now: str) -> int:
        """Every running job fails as interrupted by a restart; how many did."""
        ...
