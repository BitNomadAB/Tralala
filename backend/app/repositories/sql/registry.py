"""The registry unit of work on ``Registry``."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.engine import Connection

from ...storage.registry import Registry
from ..accounts import (
    ActorRepository,
    CredentialRepository,
    InviteRepository,
    SessionRepository,
    UserRepository,
)
from ..agents import AgentLinkRepository, AgentRepository, RoleTemplateRepository
from ..board_rows import BoardRowRepository, BoardStatsRepository
from ..code_repositories import CodeRepositoryRepository, RepositoryLinkRepository
from ..registry import RegistryUnitOfWork
from ..templates import BoardTemplateRepository
from .accounts import (
    SqlActorRepository,
    SqlCredentialRepository,
    SqlInviteRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from .agents import SqlAgentLinkRepository, SqlAgentRepository, SqlRoleTemplateRepository
from .board_rows import SqlBoardRowRepository, SqlBoardStatsRepository
from .code_repositories import SqlCodeRepositoryRepository, SqlRepositoryLinkRepository
from .templates import SqlBoardTemplateRepository


class SqlRegistryRepositories:
    """The registry repositories over one connection, inside one reader or writer."""

    def __init__(self, connection: Connection) -> None:
        # The same transaction, for code not converted yet and the infrastructure suite.
        self.connection = connection
        self.actors: ActorRepository = SqlActorRepository(connection)
        self.users: UserRepository = SqlUserRepository(connection)
        self.sessions: SessionRepository = SqlSessionRepository(connection)
        self.invites: InviteRepository = SqlInviteRepository(connection)
        self.credentials: CredentialRepository = SqlCredentialRepository(connection)
        self.boards: BoardRowRepository = SqlBoardRowRepository(connection)
        self.board_stats: BoardStatsRepository = SqlBoardStatsRepository(connection)
        self.board_templates: BoardTemplateRepository = SqlBoardTemplateRepository(connection)
        self.role_templates: RoleTemplateRepository = SqlRoleTemplateRepository(connection)
        self.agents: AgentRepository = SqlAgentRepository(connection)
        self.agent_links: AgentLinkRepository = SqlAgentLinkRepository(connection)
        self.code_repositories: CodeRepositoryRepository = SqlCodeRepositoryRepository(connection)
        self.repository_links: RepositoryLinkRepository = SqlRepositoryLinkRepository(connection)


class SqlRegistryUnitOfWork(RegistryUnitOfWork):
    """Subclasses the Protocol so pyright checks every method against it here (PEP 544).

    A writer is ``Registry.connect`` (one transaction, committed at the end, rolled back on an
    exception); a reader is ``Registry.reader`` (never commits).
    """

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    @contextmanager
    def reader(self) -> Generator[SqlRegistryRepositories]:
        with self._registry.reader() as connection:
            yield SqlRegistryRepositories(connection)

    @contextmanager
    def writer(self) -> Generator[SqlRegistryRepositories]:
        with self._registry.connect() as connection:
            yield SqlRegistryRepositories(connection)
