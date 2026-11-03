"""The unit of work of the registry database.

A service asks for ``reader()`` or ``writer()`` and works with the repositories it is handed until
the block ends. A writer commits when the block ends normally and rolls back when it raises; a
reader never commits. The SQL implementation runs on ``Registry.connect`` and ``Registry.reader``,
so a writer is exactly the transaction ``Registry.connect`` always was.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .accounts import (
    ActorRepository,
    CredentialRepository,
    InviteRepository,
    SessionRepository,
    UserRepository,
)
from .agents import AgentLinkRepository, AgentRepository, RoleTemplateRepository
from .board_rows import BoardRowRepository, BoardStatsRepository
from .code_repositories import CodeRepositoryRepository, RepositoryLinkRepository
from .templates import BoardTemplateRepository


class RegistryRepositories(Protocol):
    """The registry's repositories, inside one reader or writer."""

    @property
    def actors(self) -> ActorRepository: ...

    @property
    def users(self) -> UserRepository: ...

    @property
    def sessions(self) -> SessionRepository: ...

    @property
    def invites(self) -> InviteRepository: ...

    @property
    def credentials(self) -> CredentialRepository: ...

    @property
    def boards(self) -> BoardRowRepository: ...

    @property
    def board_stats(self) -> BoardStatsRepository: ...

    @property
    def board_templates(self) -> BoardTemplateRepository: ...

    @property
    def role_templates(self) -> RoleTemplateRepository: ...

    @property
    def agents(self) -> AgentRepository: ...

    @property
    def agent_links(self) -> AgentLinkRepository: ...

    @property
    def code_repositories(self) -> CodeRepositoryRepository: ...

    @property
    def repository_links(self) -> RepositoryLinkRepository: ...


class RegistryUnitOfWork(Protocol):
    def reader(self) -> AbstractContextManager[RegistryRepositories]: ...

    def writer(self) -> AbstractContextManager[RegistryRepositories]: ...
