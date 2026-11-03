from __future__ import annotations

import json
import logging

from ..core.config import Settings
from ..core.errors import NotFound, ServiceUnavailable
from ..storage.board_db import BoardDatabaseManager
from ..storage.migration_manager import MigrationManager, MigrationReport
from ..storage.process_lock import DataDirectoryLock
from ..storage.registry import Registry
from .agents import AgentService, RoleTemplateService
from .attachments import AttachmentService
from .auth import AuthService
from .backup_scheduler import BackupScheduler
from .backups import BackupService
from .boards import BoardService
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
        self.boards = BoardDatabaseManager(settings)
        self.migrations = MigrationManager(settings, self.registry, self.boards)
        self.board = BoardService(settings, self.registry, self.boards, self.migrations)
        self.template = TemplateService(self.registry, self.boards, self.board)
        self.board.templates = self.template
        self.role_templates = RoleTemplateService(self.registry)
        self.agent = AgentService(settings, self.registry, self.role_templates)
        self.repository = RepositoryService(settings, self.registry)
        self.repo_snapshot = RepositorySnapshotService(self.repository)
        self.board.repositories = self.repository
        self.board.agents = self.agent
        self.loop = LoopService(self.board)
        self.loop_plan = LoopPlanService(self.board, self.loop)
        self.loop_document = LoopDocumentService(self.board, self.loop, self.loop_plan)
        self.loop_links = LoopWorkflowLinks()
        self.loop_agents = LoopAgentService(self.boards, self.agent)
        self.loop_history = LoopHistoryService(self.board)
        self.loop_generation = LoopGenerationService(
            self.board,
            self.loop,
            self.loop_document,
            self.loop_links,
            self.agent,
            self.loop_agents,
            snapshots=self.repo_snapshot,
        )
        self.loop_qa = LoopQaService(
            self.board, self.loop, self.loop_history, self.loop_links
        )
        self.loop_links.bind(
            start_generation=self.loop_generation.start,
            apply_qa_instructions=self.loop_qa.apply_instructions,
        )
        self.loop.plans = self.loop_plan
        self.list = ListService(self.board, self.loop)
        self.card = CardService(self.board, self.loop, self.loop_plan)
        self.loop.cards = self.card
        self.label = LabelService(self.board)
        self.checklist = ChecklistService(self.board)
        self.comment = CommentService(self.board)
        self.search = SearchService(self.board, self.card)
        self.backup = BackupService(self.board)
        self.backup_scheduler = BackupScheduler(
            self.backup,
            interval_hours=settings.backup_interval_hours,
            keep=settings.backup_keep,
        )
        self.attachment = AttachmentService(self.board)
        self.auth = AuthService(settings, self.registry)
        self.discussion = DiscussionService(self.board, self.agent)
        self.event = EventService(self.board)
        self.orchestrator = Orchestrator(settings, self.board, self.event)
        self.run = RunService(settings, self.board, self.orchestrator, self.event)
        self.discussion.runs = self.run
        self.discussion.events = self.event
        self.mention = MentionService(settings, self.board, self.agent, self.event)
        self.comment.mentions = self.mention
        self.data_lock = DataDirectoryLock(settings.data_dir)
        self.migration_reports: list[MigrationReport] = []

    def initialize(self) -> None:
        """Take the data directory, then migrate, before the application accepts requests."""
        self.data_lock.acquire()
        self.migrations.migrate_registry()
        self.registry.bootstrap_admin()
        self.role_templates.seed_defaults()
        resealed = self.agent.reseal_credentials()
        if resealed:
            logger.info(
                json.dumps({"event": "agent_credentials_resealed", "items": resealed})
            )
        resealed_repositories = self.repository.reseal_tokens()
        if resealed_repositories:
            logger.info(
                json.dumps(
                    {"event": "repository_tokens_resealed", "items": resealed_repositories}
                )
            )
        self.board.recover()
        self.migration_reports = self.migrations.migrate_all_boards()
        self.recover_async_work()
        self.backup_scheduler.start()

    def recover_async_work(self) -> int:
        """Resolve runs and mention jobs interrupted by the previous process stopping."""
        recovered = 0
        for row in self.registry.read("SELECT id FROM boards"):
            try:
                recovered += self.run.recover(row["id"])
                recovered += self.mention.recover(row["id"])
                recovered += self.loop_generation.recover(row["id"])
            except (NotFound, ServiceUnavailable):
                # A board mid-repair is resolved above or on its next start; never block startup.
                continue
        if recovered:
            logger.info(
                json.dumps({"event": "async_work_recovered", "items": recovered})
            )
        return recovered

    def shutdown(self) -> None:
        self.backup_scheduler.stop()
        self.run.shutdown()
        self.mention.shutdown()
        self.loop_generation.shutdown()
        self.event.shutdown()
        self.boards.close_all()
        self.registry.dispose()
        self.data_lock.release()



