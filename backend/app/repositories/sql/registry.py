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
from ..registry import RegistryUnitOfWork
from .accounts import (
    SqlActorRepository,
    SqlCredentialRepository,
    SqlInviteRepository,
    SqlSessionRepository,
    SqlUserRepository,
)


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
