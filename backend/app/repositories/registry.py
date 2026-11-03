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


class RegistryUnitOfWork(Protocol):
    def reader(self) -> AbstractContextManager[RegistryRepositories]: ...

    def writer(self) -> AbstractContextManager[RegistryRepositories]: ...
