from __future__ import annotations

import logging

from ..core.config import Settings
from ..repositories.sql.backups import SqliteBoardSnapshots
from ..repositories.sql.board import (
    SqlBoardUnitOfWork,
    board_files,
    board_migrator,
    full_text_index,
)
from ..repositories.sql.registry import SqlRegistryUnitOfWork
from ..storage.board_db import BoardDatabaseManager
from ..storage.data_files import BootstrapPasswordFileOnDisk
from ..storage.migration_manager import MigrationManager, MigrationReport
from ..storage.process_lock import DataDirectoryLock
from ..storage.registry import Registry
from ..storage.schema import runner
from . import recovery
from .agents import AgentService, RoleTemplateService
from .attachments import AttachmentService
from .auth import AuthService
from .backup_scheduler import BackupScheduler
from .backups import BackupService
from .board_stats import BoardStatsCache
from .boards import BoardSchema, BoardService
from .cards import CardService
from .discussions import DiscussionService
from .events import EventService
from .lists import ListService
from .loop_agents import LoopAgentService
from .loop_documents import LoopDocumentService
from .loop_generation import LoopGenerationService
from .loop_history import LoopHistoryService
from .loop_links import LoopWorkflowLinks
from .loop_plans import LoopPlanService
from .loop_qa import LoopQaService
from .loops import LoopService
from .mentions import MentionService
from .orchestrator import Orchestrator
from .repo_mirror import MirrorService
from .repo_mirror_files import DiskMirrorFiles
from .repo_mirror_git import SubprocessGit
from .repo_snapshot import RepositorySnapshotService
from .repositories import RepositoryService
from .runs import RunService
from .search import SearchService
from .subresources import ChecklistService, CommentService, LabelService
from .templates import TemplateService

logger = logging.getLogger("tralala")


class Services:
    """Single composition root shared by every interface (REST and WebMCP)."""

    def __init__(self, settings: Settings) -> None:
        settings.ensure_dirs()
        self.settings = settings
        self.registry = Registry(settings)
        # The registry unit of work: the one way a service reaches the registry.
        self.registry_store = SqlRegistryUnitOfWork(self.registry)
        self.boards = BoardDatabaseManager(settings)
        # The board unit of work: the one way a service reaches a board database.
        self.board_store = SqlBoardUnitOfWork(self.boards)
        self.board_stats = BoardStatsCache(settings, self.registry_store, self.board_store)
        # The manager has exactly one write choke point, so the cache is told there instead of
        # asking every service to remember to invalidate.
        self.boards.on_write = self.board_stats.invalidate
        self.migrations = MigrationManager(settings, self.registry, self.boards)
        self.role_templates = RoleTemplateService(self.registry_store)
        self.agent = AgentService(settings, self.registry_store)
        # The Git mirrors of the ``git_https`` repositories: the real git program and the real
        # files under <data>/repos, the only two things the mirror service does not decide itself.
        self.repository_mirror = MirrorService(
            SubprocessGit(settings.repository_git_binary, settings.repos_dir),
            DiskMirrorFiles(settings.repos_dir, profile=settings.file_profile),
            hosts=settings.allowed_repository_hosts,
            max_bytes=settings.repository_mirror_max_bytes,
            timeout_seconds=settings.repository_fetch_timeout_seconds,
        )
        self.repository = RepositoryService(
            settings, self.registry_store, mirror=self.repository_mirror
        )
        self.repo_snapshot = RepositorySnapshotService(
            self.repository, mirror=self.repository_mirror
        )
        self.board = BoardService(
            settings,
            self.registry_store,
            self.board_store,
            board_files(self.boards),
            migrations=board_migrator(self.migrations),
            schema=BoardSchema(
                head_revision=runner.head_revision("board"),
                version=runner.revision_count("board"),
            ),
            stats=self.board_stats,
            agents=self.agent,
            repositories=self.repository,
        )
        self.template = TemplateService(self.registry_store, self.board_store, self.board)
        self.board.templates = self.template
        # The plan service works inside its caller's unit of work and is the plan views the
        # Loop, Ticket and search services read.
        self.loop_plan = LoopPlanService()
        self.card = CardService(
            settings, self.board, self.board_store, self.registry_store, plans=self.loop_plan
        )
        self.loop = LoopService(
            settings, self.board, self.board_store, plans=self.loop_plan, tickets=self.card
        )
        self.loop_document = LoopDocumentService(self.board, self.board_store, self.loop_plan)
        self.loop_links = LoopWorkflowLinks()
        self.loop_agents = LoopAgentService(self.board_store, self.agent)
        self.loop_history = LoopHistoryService(
            self.board, self.board_store, self.boards, self.boards
        )
        self.loop_generation = LoopGenerationService(
            settings,
            self.board,
            self.board_store,
            self.registry_store,
            self.loop_document,
            self.loop_links,
            self.agent,
            self.loop_agents,
            snapshots=self.repo_snapshot,
            idempotency_ttl_seconds=settings.idempotency_ttl_seconds,
            context_chars=settings.generation_context_chars,
        )
        self.loop_qa = LoopQaService(
            self.board,
            self.board_store,
            self.loop_history,
            self.loop_links,
            idempotency_ttl_seconds=settings.idempotency_ttl_seconds,
        )
        self.loop_links.bind(
            start_generation=self.loop_generation.start,
            apply_qa_instructions=self.loop_qa.apply_instructions,
        )
        self.list = ListService(self.board, self.board_store)
        self.label = LabelService(self.board, self.board_store)
        self.checklist = ChecklistService(self.board, self.board_store)
        self.comment = CommentService(self.board, self.board_store, self.registry_store)
        self.search = SearchService(
            self.board,
            self.board_store,
            self.registry_store,
            plans=self.loop_plan,
            index=full_text_index(self.boards),
        )
        self.backup = BackupService(
            self.board,
            self.boards,
            SqliteBoardSnapshots(self.boards),
            backups_dir=settings.backups_dir,
            file_profile=settings.file_profile,
        )
        self.backup_scheduler = BackupScheduler(
            self.backup,
            store=self.registry_store,
            interval_hours=settings.backup_interval_hours,
            keep=settings.backup_keep,
        )
        self.attachment = AttachmentService(
            settings, self.board, self.board_store, board_files(self.boards)
        )
        self.auth = AuthService(
            settings,
            self.registry_store,
            bootstrap_password_file=BootstrapPasswordFileOnDisk(
                settings.data_dir, profile=settings.file_profile
            ),
        )
        self.discussion = DiscussionService(
            self.board, self.agent, self.board_store, self.registry_store
        )
        self.event = EventService(self.board, self.board_store)
        self.orchestrator = Orchestrator(
            settings, self.board_store, self.registry_store, self.event
        )
        self.run = RunService(
            settings, self.board, self.orchestrator, self.board_store, self.event
        )
        self.discussion.runs = self.run
        self.discussion.events = self.event
        self.mention = MentionService(
            settings,
            self.board,
            self.agent,
            self.board_store,
            self.registry_store,
            self.boards,
            self.event,
        )
        self.comment.mentions = self.mention
        self.data_lock = DataDirectoryLock(settings.data_dir)
        self.migration_reports: list[MigrationReport] = []

    def initialize(self) -> None:
        """Take the data directory, then migrate, before the application accepts requests."""
        self.data_lock.acquire()
        self.migrations.migrate_registry()
        self.auth.bootstrap_admin()
        self.role_templates.seed_defaults()
        resealed = self.agent.reseal_credentials()
        if resealed:
            logger.info("agent_credentials_resealed", extra={"items": resealed})
        resealed_repositories = self.repository.reseal_tokens()
        if resealed_repositories:
            logger.info("repository_tokens_resealed", extra={"items": resealed_repositories})
        self.board.recover()
        self.migration_reports = self.migrations.migrate_all_boards()
        self.recover_async_work()
        self.backup_scheduler.start()

    def recover_async_work(self) -> int:
        """Resolve runs and mention jobs interrupted by the previous process stopping."""
        board_ids = [str(row["id"]) for row in self.registry.read("SELECT id FROM boards")]
        return recovery.recover_async_work(
            board_ids, (self.run.recover, self.mention.recover, self.loop_generation.recover)
        )

    def shutdown(self) -> None:
        self.backup_scheduler.stop()
        self.run.shutdown()
        self.mention.shutdown()
        self.loop_generation.shutdown()
        self.event.shutdown()
        self.boards.close_all()
        self.registry.dispose()
        self.data_lock.release()
