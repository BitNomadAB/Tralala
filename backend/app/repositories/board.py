"""The unit of work of one board database.

A service asks for ``reader(board_id)`` or ``writer(board_id)`` and works with the repositories it
is handed until the block ends. A writer commits when the block ends normally and rolls back when
it raises; a reader never commits. The SQL implementation runs on ``BoardDatabaseManager``, so the
per-board lock, the transaction and the write notification stay where they are.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .activity import ActivityRepository
from .attachments import AttachmentRepository
from .board_metadata import BoardMetadataRepository, LoopDefaultsRepository
from .cards import CardRepository
from .checklists import ChecklistItemRepository, ChecklistRepository
from .comments import CommentRepository
from .counters import CounterRepository
from .discussions import (
    DiscussionMessageRepository,
    DiscussionOutcomeRepository,
    DiscussionParticipantRepository,
    DiscussionRoundRepository,
    DiscussionRunRepository,
    DiscussionThreadRepository,
    DiscussionVoteRepository,
)
from .events import EventRepository
from .generation_runs import GenerationRunRepository
from .idempotency import BoardIdempotencyRepository
from .labels import LabelRepository
from .lists import ListRepository
from .loop_agents import LoopAgentRepository
from .loop_documents import LoopApprovalRepository, LoopDocumentRepository
from .loop_history import LoopArchiveRepository, LoopHistoryRepository
from .loop_notes import LoopNoteRepository
from .loop_plans import (
    LoopDependencyRepository,
    LoopPhaseRepository,
    LoopPlanItemRepository,
    LoopPlanRepository,
)
from .loop_qa import LoopQaRepository
from .loops import LoopRepository
from .mention_jobs import MentionJobRepository
from .search import CardSearchRepository


class BoardRepositories(Protocol):
    """The repositories of one board, inside one reader or writer."""

    @property
    def lists(self) -> ListRepository: ...

    @property
    def loops(self) -> LoopRepository: ...

    @property
    def activity(self) -> ActivityRepository: ...

    @property
    def labels(self) -> LabelRepository: ...

    @property
    def counters(self) -> CounterRepository: ...

    @property
    def metadata(self) -> BoardMetadataRepository: ...

    @property
    def loop_defaults(self) -> LoopDefaultsRepository: ...

    @property
    def cards(self) -> CardRepository: ...

    @property
    def documents(self) -> LoopDocumentRepository: ...

    @property
    def approvals(self) -> LoopApprovalRepository: ...

    @property
    def plans(self) -> LoopPlanRepository: ...

    @property
    def phases(self) -> LoopPhaseRepository: ...

    @property
    def plan_items(self) -> LoopPlanItemRepository: ...

    @property
    def dependencies(self) -> LoopDependencyRepository: ...

    @property
    def qa(self) -> LoopQaRepository: ...

    @property
    def idempotency(self) -> BoardIdempotencyRepository: ...

    @property
    def checklists(self) -> ChecklistRepository: ...

    @property
    def checklist_items(self) -> ChecklistItemRepository: ...

    @property
    def comments(self) -> CommentRepository: ...

    @property
    def notes(self) -> LoopNoteRepository: ...

    @property
    def attachments(self) -> AttachmentRepository: ...

    @property
    def search(self) -> CardSearchRepository: ...

    @property
    def loop_agents(self) -> LoopAgentRepository: ...

    @property
    def events(self) -> EventRepository: ...

    @property
    def threads(self) -> DiscussionThreadRepository: ...

    @property
    def messages(self) -> DiscussionMessageRepository: ...

    @property
    def participants(self) -> DiscussionParticipantRepository: ...

    @property
    def votes(self) -> DiscussionVoteRepository: ...

    @property
    def runs(self) -> DiscussionRunRepository: ...

    @property
    def rounds(self) -> DiscussionRoundRepository: ...

    @property
    def outcomes(self) -> DiscussionOutcomeRepository: ...

    @property
    def mention_jobs(self) -> MentionJobRepository: ...

    @property
    def generation_runs(self) -> GenerationRunRepository: ...

    @property
    def archive(self) -> LoopArchiveRepository: ...

    @property
    def history(self) -> LoopHistoryRepository: ...

    def savepoint(self) -> AbstractContextManager[None]:
        """A nested transaction inside a writer: it keeps its writes when the block ends normally
        and undoes only them when it raises, so one failed item of a batch leaves the others."""
        ...


class BoardUnitOfWork(Protocol):
    def exists(self, board_id: str) -> bool:
        """Whether the board's database exists; it says nothing about the registry row."""
        ...

    def reader(self, board_id: str) -> AbstractContextManager[BoardRepositories]: ...

    def writer(self, board_id: str) -> AbstractContextManager[BoardRepositories]: ...
