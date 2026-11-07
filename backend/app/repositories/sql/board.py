"""The board unit of work on ``BoardDatabaseManager``."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.engine import Connection

from ...storage.board_db import BoardDatabaseManager
from ...storage.migration_manager import MigrationManager
from ..activity import ActivityRepository
from ..attachments import AttachmentRepository
from ..board import BoardUnitOfWork
from ..board_files import BoardFiles, BoardMigrator
from ..board_metadata import BoardMetadataRepository, LoopDefaultsRepository
from ..card_notes import CardNoteRepository
from ..cards import CardRepository
from ..checklists import ChecklistItemRepository, ChecklistRepository
from ..comments import CommentRepository
from ..counters import CounterRepository
from ..discussions import (
    DiscussionMessageRepository,
    DiscussionOutcomeRepository,
    DiscussionParticipantRepository,
    DiscussionRoundRepository,
    DiscussionRunRepository,
    DiscussionThreadRepository,
    DiscussionVoteRepository,
)
from ..events import EventRepository
from ..generation_runs import GenerationRunRepository
from ..idempotency import BoardIdempotencyRepository
from ..labels import LabelRepository
from ..lists import ListRepository
from ..loop_agents import LoopAgentRepository
from ..loop_documents import LoopApprovalRepository, LoopDocumentRepository
from ..loop_history import LoopArchiveRepository, LoopHistoryRepository
from ..loop_notes import LoopNoteRepository
from ..loop_plans import (
    LoopDependencyRepository,
    LoopPhaseRepository,
    LoopPlanItemRepository,
    LoopPlanRepository,
)
from ..loop_qa import LoopQaRepository
from ..loops import LoopRepository
from ..mention_jobs import MentionJobRepository
from ..search import CardSearchRepository, FullTextIndex
from .activity import SqlActivityRepository
from .attachments import SqlAttachmentRepository
from .board_metadata import SqlBoardMetadataRepository, SqlLoopDefaultsRepository
from .card_notes import SqlCardNoteRepository
from .cards import SqlCardRepository
from .checklists import SqlChecklistItemRepository, SqlChecklistRepository
from .comments import SqlCommentRepository
from .counters import SqlCounterRepository
from .discussions import (
    SqlDiscussionMessageRepository,
    SqlDiscussionOutcomeRepository,
    SqlDiscussionParticipantRepository,
    SqlDiscussionRoundRepository,
    SqlDiscussionRunRepository,
    SqlDiscussionThreadRepository,
    SqlDiscussionVoteRepository,
)
from .events import SqlEventRepository
from .generation_runs import SqlGenerationRunRepository
from .idempotency import SqlBoardIdempotencyRepository
from .labels import SqlLabelRepository
from .lists import SqlListRepository
from .loop_agents import SqlLoopAgentRepository
from .loop_documents import SqlLoopApprovalRepository, SqlLoopDocumentRepository
from .loop_history import SqlLoopArchiveRepository, SqlLoopHistoryRepository
from .loop_notes import SqlLoopNoteRepository
from .loop_plans import (
    SqlLoopDependencyRepository,
    SqlLoopPhaseRepository,
    SqlLoopPlanItemRepository,
    SqlLoopPlanRepository,
)
from .loop_qa import SqlLoopQaRepository
from .loops import SqlLoopRepository
from .mention_jobs import SqlMentionJobRepository
from .search import SqlCardSearchRepository


class SqlBoardRepositories:
    """The board repositories over one connection, inside one reader or writer."""

    def __init__(self, connection: Connection) -> None:
        # The reader's or writer's connection: the savepoint nests in it, and the infrastructure
        # suite probes the transaction through it.
        self.connection = connection
        self.lists: ListRepository = SqlListRepository(connection)
        self.loops: LoopRepository = SqlLoopRepository(connection)
        self.activity: ActivityRepository = SqlActivityRepository(connection)
        self.labels: LabelRepository = SqlLabelRepository(connection)
        self.counters: CounterRepository = SqlCounterRepository(connection)
        self.metadata: BoardMetadataRepository = SqlBoardMetadataRepository(connection)
        self.loop_defaults: LoopDefaultsRepository = SqlLoopDefaultsRepository(connection)
        self.cards: CardRepository = SqlCardRepository(connection)
        self.documents: LoopDocumentRepository = SqlLoopDocumentRepository(connection)
        self.approvals: LoopApprovalRepository = SqlLoopApprovalRepository(connection)
        self.plans: LoopPlanRepository = SqlLoopPlanRepository(connection)
        self.phases: LoopPhaseRepository = SqlLoopPhaseRepository(connection)
        self.plan_items: LoopPlanItemRepository = SqlLoopPlanItemRepository(connection)
        self.dependencies: LoopDependencyRepository = SqlLoopDependencyRepository(connection)
        self.qa: LoopQaRepository = SqlLoopQaRepository(connection)
        self.idempotency: BoardIdempotencyRepository = SqlBoardIdempotencyRepository(connection)
        self.checklists: ChecklistRepository = SqlChecklistRepository(connection)
        self.checklist_items: ChecklistItemRepository = SqlChecklistItemRepository(connection)
        self.comments: CommentRepository = SqlCommentRepository(connection)
        self.card_notes: CardNoteRepository = SqlCardNoteRepository(connection)
        self.notes: LoopNoteRepository = SqlLoopNoteRepository(connection)
        self.attachments: AttachmentRepository = SqlAttachmentRepository(connection)
        self.search: CardSearchRepository = SqlCardSearchRepository(connection)
        self.loop_agents: LoopAgentRepository = SqlLoopAgentRepository(connection)
        self.events: EventRepository = SqlEventRepository(connection)
        self.threads: DiscussionThreadRepository = SqlDiscussionThreadRepository(connection)
        self.messages: DiscussionMessageRepository = SqlDiscussionMessageRepository(connection)
        self.participants: DiscussionParticipantRepository = (
            SqlDiscussionParticipantRepository(connection)
        )
        self.votes: DiscussionVoteRepository = SqlDiscussionVoteRepository(connection)
        self.runs: DiscussionRunRepository = SqlDiscussionRunRepository(connection)
        self.rounds: DiscussionRoundRepository = SqlDiscussionRoundRepository(connection)
        self.outcomes: DiscussionOutcomeRepository = SqlDiscussionOutcomeRepository(connection)
        self.mention_jobs: MentionJobRepository = SqlMentionJobRepository(connection)
        self.generation_runs: GenerationRunRepository = SqlGenerationRunRepository(connection)
        self.archive: LoopArchiveRepository = SqlLoopArchiveRepository(connection)
        self.history: LoopHistoryRepository = SqlLoopHistoryRepository(connection)

    @contextmanager
    def savepoint(self) -> Generator[None]:
        with self.connection.begin_nested():
            yield


class SqlBoardUnitOfWork(BoardUnitOfWork):
    """Subclasses the Protocol so pyright checks every method against it here (PEP 544)."""

    def __init__(self, boards: BoardDatabaseManager) -> None:
        self._boards = boards

    def exists(self, board_id: str) -> bool:
        return self._boards.exists(board_id)

    @contextmanager
    def reader(self, board_id: str) -> Generator[SqlBoardRepositories]:
        with self._boards.reader(board_id) as connection:
            yield SqlBoardRepositories(connection)

    @contextmanager
    def writer(self, board_id: str) -> Generator[SqlBoardRepositories]:
        with self._boards.session(board_id) as connection:
            yield SqlBoardRepositories(connection)


def board_files(boards: BoardDatabaseManager) -> BoardFiles:
    """The manager is the board's files; pyright proves the Protocol here."""
    return boards


def board_migrator(migrations: MigrationManager) -> BoardMigrator:
    """The Migration Manager migrates a board; pyright proves the Protocol here."""
    return migrations


def full_text_index(boards: BoardDatabaseManager) -> FullTextIndex:
    """The manager knows which boards have the FTS5 card index; pyright proves the Protocol here."""
    return boards
