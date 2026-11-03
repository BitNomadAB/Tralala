"""People, their sessions and invitations, and the API tokens they issue, for ``AuthService``.

Every row here lives in the registry database. A person is an ``actors`` row of type ``user`` plus
its ``user_credentials`` row (password hash, role, appearance); an API token is an
``api_credentials`` row plus the ``agent`` actor it acts as. Joined reads return the generated rows
side by side in a small frozen value, never a merged dictionary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db.generated.registry import (
    ActorsRow,
    ApiCredentialsRow,
    SessionsRow,
    UserCredentialsRow,
    UserInvitesRow,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class User:
    """A person: the actor and its sign-in record."""

    actor: ActorsRow
    credentials: UserCredentialsRow


@dataclass(frozen=True, slots=True, kw_only=True)
class ActorSession:
    """A session with the actor it belongs to; ``role`` is None for an actor without a sign-in."""

    session: SessionsRow
    actor: ActorsRow
    role: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Invitation:
    """An enrolment invitation with the person it was issued for."""

    invite: UserInvitesRow
    actor: ActorsRow


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedToken:
    """An API token with the agent actor it acts as and the name of the person who owns it."""

    credential: ApiCredentialsRow
    actor: ActorsRow
    owner_name: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerTokens:
    """How many live (unrevoked) tokens one person owns, and when one was last used."""

    live: int
    last_used_at: str | None


class ActorRepository(Protocol):
    def any_user(self) -> bool:
        """Whether any person exists, enabled or not."""
        ...

    def add(self, row: ActorsRow) -> None: ...

    def disable(self, actor_id: str, *, now: str) -> None:
        """Disable the actor; one that is already disabled keeps its first ``disabled_at``."""
        ...

    def enable(self, actor_id: str) -> None: ...


class UserRepository(Protocol):
    def get(self, actor_id: str) -> User | None:
        """The person, enabled or disabled."""
        ...

    def enabled_by_name(self, name: str) -> User | None: ...

    def all(self) -> list[User]:
        """Every person, enabled or disabled, oldest first (then by name)."""
        ...

    def credentials(self, actor_id: str) -> UserCredentialsRow | None: ...

    def add(self, row: UserCredentialsRow) -> None:
        """The sign-in record of a person whose actor row exists."""
        ...

    def set_role(self, actor_id: str, role: str) -> None:
        """Change the role; ``updated_at`` stays, as it records the password."""
        ...

    def set_password(self, actor_id: str, password_hash: str, *, now: str) -> None: ...

    def set_preferences(
        self, actor_id: str, *, theme_mode: str | None, theme_kit: str | None, now: str
    ) -> None: ...

    def count_enabled_admins(self, *, exclude: str) -> int:
        """Enabled administrators other than ``exclude``."""
        ...


class SessionRepository(Protocol):
    def add(self, row: SessionsRow) -> None: ...

    def by_token_hash(self, token_hash: str) -> ActorSession | None: ...

    def touch(self, session_id: str, *, now: str, seen_before: str) -> None:
        """Set ``last_seen_at`` to ``now``, only when it is older than ``seen_before``."""
        ...

    def revoke(self, token_hash: str, *, now: str) -> bool:
        """Revoke the session if it is live; whether one was."""
        ...

    def revoke_for_actor(self, actor_id: str, *, now: str) -> int:
        """Revoke every live session of the actor; how many were live."""
        ...

    def purge(self, *, now: str) -> int:
        """Delete the sessions that expired before ``now`` or were revoked; how many."""
        ...


class InviteRepository(Protocol):
    def by_token_hash(self, token_hash: str) -> Invitation | None: ...

    def add(self, row: UserInvitesRow) -> None: ...

    def delete_unused(self, actor_id: str) -> None:
        """Delete the person's invitations that were never used."""
        ...

    def mark_used(self, invite_id: str, *, now: str) -> None: ...


class CredentialRepository(Protocol):
    def get(self, credential_id: str) -> IssuedToken | None: ...

    def by_token_hash(self, token_hash: str) -> IssuedToken | None: ...

    def listing(self, owner_actor_id: str | None) -> list[IssuedToken]:
        """Newest first, revoked ones included; ``owner_actor_id`` keeps one person's tokens."""
        ...

    def owner_counts(self) -> dict[str, OwnerTokens]:
        """Per owning person, their live tokens; a person without one is absent."""
        ...

    def add(self, row: ApiCredentialsRow) -> None: ...

    def touch(self, credential_id: str, *, now: str) -> None:
        """Record a use of the token."""
        ...

    def revoke(self, credential_id: str, *, now: str) -> bool:
        """Revoke the token if it is live; whether it was."""
        ...

    def live_actor_ids(self, owner_actor_id: str) -> list[str]:
        """The agent actors behind the person's live tokens."""
        ...

    def revoke_by_owner(self, owner_actor_id: str, *, now: str) -> None:
        """Revoke every live token the person owns."""
        ...
