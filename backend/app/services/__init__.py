from __future__ import annotations

import json
import logging

from ..core.config import Settings
from ..core.errors import NotFound, ServiceUnavailable
from ..storage.board_db import BoardDatabaseManager
from ..storage.migration_manager import MigrationManager, MigrationReport
from ..storage.registry import Registry
from .agents import AgentService, RoleTemplateService
from .attachments import AttachmentService
from .auth import AuthService
from .backups import BackupService
from .boards import BoardService
from .cards import CardService
from .discussions import DiscussionService
from .events import EventService
from .lists import ListService
from .loop_documents import LoopDocumentService
from .loop_generation import LoopGenerationService
from .loop_history import LoopHistoryService
from .loop_plans import LoopPlanService
from .loop_qa import LoopQaService
from .loops import LoopService
from .mentions import MentionService
from .orchestrator import Orchestrator
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
        self.loop = LoopService(self.board)
        self.loop_plan = LoopPlanService(self.board, self.loop)
        self.loop_document = LoopDocumentService(self.board, self.loop, self.loop_plan)
        self.loop_generation = LoopGenerationService(
            self.board, self.loop, self.loop_document
        )
        self.loop_history = LoopHistoryService(self.board)
        self.loop_qa = LoopQaService(self.board, self.loop)
        self.loop_qa.history = self.loop_history
        self.loop_qa.generation = self.loop_generation
        self.loop_generation.qa = self.loop_qa
        self.loop.plans = self.loop_plan
        self.list = ListService(self.board, self.loop)
        self.card = CardService(self.board, self.loop, self.loop_plan)
        self.loop.cards = self.card
        self.label = LabelService(self.board)
        self.checklist = ChecklistService(self.board)
        self.comment = CommentService(self.board)
        self.search = SearchService(self.board, self.card)
        self.backup = BackupService(self.board)
        self.attachment = AttachmentService(self.board)
        self.auth = AuthService(settings, self.registry)
        self.role_templates = RoleTemplateService(self.registry)
        self.agent = AgentService(settings, self.registry, self.role_templates)
        self.discussion = DiscussionService(self.board, self.agent)
        self.event = EventService(self.board)
        self.orchestrator = Orchestrator(settings, self.board, self.event)
        self.run = RunService(settings, self.board, self.orchestrator, self.event)
        self.discussion.runs = self.run
        self.discussion.events = self.event
        self.mention = MentionService(settings, self.board, self.agent, self.event)
        self.comment.mentions = self.mention
        self.migration_reports: list[MigrationReport] = []

    def initialize(self) -> None:
        """Registry first, then every board, before the application accepts requests."""
        self.migrations.migrate_registry()
        self.registry.bootstrap_admin()
        self.role_templates.seed_defaults()
        resealed = self.agent.reseal_credentials()
        if resealed:
            logger.info(
                json.dumps({"event": "agent_credentials_resealed", "items": resealed})
            )
        self.board.recover()
        self.migration_reports = self.migrations.migrate_all_boards()
        self.recover_async_work()

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
        self.run.shutdown()
        self.mention.shutdown()
        self.loop_generation.shutdown()
        self.event.shutdown()
        self.boards.close_all()
        self.registry.dispose()



