"""The registry database in memory: the account repositories and their unit of work."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.db.generated.registry import (
    ActorsRow,
    ApiCredentialsRow,
    SessionsRow,
    UserCredentialsRow,
    UserInvitesRow,
)
from app.repositories.accounts import (
    ActorRepository,
    ActorSession,
    CredentialRepository,
    Invitation,
    InviteRepository,
    IssuedToken,
    OwnerTokens,
    SessionRepository,
    User,
    UserRepository,
)
from app.repositories.registry import RegistryUnitOfWork

CREATED = "2026-11-01T09:00:00Z"


class ConstraintError(Exception):
    """What SQLite would refuse (a primary, unique or foreign key): a test that sees it found
    a bug."""


@dataclass(slots=True)
class RegistryState:
    """The account rows of the registry, as a test sets them up and the services change them.

    Dictionaries keep insertion order, which stands in for SQLite's row order where a statement has
    no ``ORDER BY``.
    """

    actors: dict[str, ActorsRow] = field(default_factory=dict[str, ActorsRow])
    sign_ins: dict[str, UserCredentialsRow] = field(default_factory=dict[str, UserCredentialsRow])
    sessions: dict[str, SessionsRow] = field(default_factory=dict[str, SessionsRow])
    invites: dict[str, UserInvitesRow] = field(default_factory=dict[str, UserInvitesRow])
    credentials: dict[str, ApiCredentialsRow] = field(
        default_factory=dict[str, ApiCredentialsRow]
    )

    def snapshot(self) -> RegistryState:
        return RegistryState(
            dict(self.actors),
            dict(self.sign_ins),
            dict(self.sessions),
            dict(self.invites),
            dict(self.credentials),
        )

    def restore(self, snapshot: RegistryState) -> None:
        self.actors = snapshot.actors
        self.sign_ins = snapshot.sign_ins
        self.sessions = snapshot.sessions
        self.invites = snapshot.invites
        self.credentials = snapshot.credentials


def _require_actor(state: RegistryState, actor_id: str) -> None:
    """The foreign key every account row holds on ``actors``."""
    if actor_id not in state.actors:
        raise ConstraintError(f"actors.id {actor_id} does not exist")


# --- rows for a test to start from ---------------------------------------------------------------


def actor_row(
    actor_id: str,
    *,
    type_: str = "user",
    name: str = "",
    created_at: str = CREATED,
    disabled_at: str | None = None,
) -> ActorsRow:
    return ActorsRow(
        id=actor_id,
        type=type_,
        name=name or f"Actor {actor_id}",
        created_at=created_at,
        disabled_at=disabled_at,
    )


def sign_in_row(
    actor_id: str,
    *,
    password_hash: str = "",
    role: str = "member",
    theme_mode: str | None = None,
    theme_kit: str | None = None,
) -> UserCredentialsRow:
    return UserCredentialsRow(
        actor_id=actor_id,
        password_hash=password_hash or f"hashed:{actor_id}",
        updated_at=CREATED,
        role=role,
        theme_mode=theme_mode,
        theme_kit=theme_kit,
    )


def session_row(
    session_id: str,
    actor_id: str,
    *,
    token_hash: str,
    expires_at: str,
    last_seen_at: str = CREATED,
    revoked_at: str | None = None,
) -> SessionsRow:
    return SessionsRow(
        id=session_id,
        token_hash=token_hash,
        actor_id=actor_id,
        created_at=CREATED,
        expires_at=expires_at,
        last_seen_at=last_seen_at,
        revoked_at=revoked_at,
    )


def credential_row(
    credential_id: str,
    actor_id: str,
    *,
    token_hash: str = "",
    scopes: str = '["boards:read"]',
    owner_actor_id: str | None = None,
    created_at: str = CREATED,
    expires_at: str | None = None,
    last_used_at: str | None = None,
    revoked_at: str | None = None,
) -> ApiCredentialsRow:
    return ApiCredentialsRow(
        id=credential_id,
        actor_id=actor_id,
        name=f"Token {credential_id}",
        token_hash=token_hash or f"digest:{credential_id}",
        scopes=scopes,
        created_at=created_at,
        expires_at=expires_at,
        last_used_at=last_used_at,
        revoked_at=revoked_at,
        owner_actor_id=owner_actor_id,
    )


def invite_row(
    invite_id: str,
    actor_id: str,
    *,
    token_hash: str,
    expires_at: str,
    created_by_actor_id: str = "admin",
    used_at: str | None = None,
) -> UserInvitesRow:
    return UserInvitesRow(
        id=invite_id,
        actor_id=actor_id,
        token_hash=token_hash,
        created_by_actor_id=created_by_actor_id,
        created_at=CREATED,
        expires_at=expires_at,
        used_at=used_at,
    )


# --- repositories --------------------------------------------------------------------------------


class FakeActorRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def any_user(self) -> bool:
        return any(actor.type == "user" for actor in self._state.actors.values())

    def add(self, row: ActorsRow) -> None:
        if row.id in self._state.actors:
            raise ConstraintError(f"actors.id {row.id} exists")
        self._state.actors[row.id] = row

    def disable(self, actor_id: str, *, now: str) -> None:
        actor = self._state.actors.get(actor_id)
        if actor is not None and actor.disabled_at is None:
            self._state.actors[actor_id] = actor.__replace__(disabled_at=now)

    def enable(self, actor_id: str) -> None:
        actor = self._state.actors.get(actor_id)
        if actor is not None:
            self._state.actors[actor_id] = actor.__replace__(disabled_at=None)


class FakeUserRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _users(self) -> list[User]:
        return [
            User(actor=actor, credentials=self._state.sign_ins[actor.id])
            for actor in self._state.actors.values()
            if actor.type == "user" and actor.id in self._state.sign_ins
        ]

    def get(self, actor_id: str) -> User | None:
        return next((user for user in self._users() if user.actor.id == actor_id), None)

    def enabled_by_name(self, name: str) -> User | None:
        return next(
            (
                user
                for user in self._users()
                if user.actor.name == name and user.actor.disabled_at is None
            ),
            None,
        )

    def all(self) -> list[User]:
        return sorted(self._users(), key=lambda user: (user.actor.created_at, user.actor.name))

    def credentials(self, actor_id: str) -> UserCredentialsRow | None:
        return self._state.sign_ins.get(actor_id)

    def add(self, row: UserCredentialsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.actor_id in self._state.sign_ins:
            raise ConstraintError(f"user_credentials.actor_id {row.actor_id} exists")
        self._state.sign_ins[row.actor_id] = row

    def _change(self, actor_id: str, row: UserCredentialsRow) -> None:
        self._state.sign_ins[actor_id] = row

    def set_role(self, actor_id: str, role: str) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None and row.role != role:
            self._change(actor_id, row.__replace__(role=role))

    def set_password(self, actor_id: str, password_hash: str, *, now: str) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None:
            self._change(actor_id, row.__replace__(password_hash=password_hash, updated_at=now))

    def set_preferences(
        self, actor_id: str, *, theme_mode: str | None, theme_kit: str | None, now: str
    ) -> None:
        row = self._state.sign_ins.get(actor_id)
        if row is not None:
            changed = row.__replace__(theme_mode=theme_mode, theme_kit=theme_kit, updated_at=now)
            self._change(actor_id, changed)

    def count_enabled_admins(self, *, exclude: str) -> int:
        return sum(
            1
            for user in self._users()
            if user.actor.disabled_at is None
            and user.credentials.role == "admin"
            and user.actor.id != exclude
        )


class FakeSessionRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def add(self, row: SessionsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.sessions:
            raise ConstraintError(f"sessions.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.sessions.values()):
            raise ConstraintError("sessions.token_hash is unique")
        self._state.sessions[row.id] = row

    def by_token_hash(self, token_hash: str) -> ActorSession | None:
        for session in self._state.sessions.values():
            actor = self._state.actors.get(session.actor_id)
            if session.token_hash == token_hash and actor is not None:
                sign_in = self._state.sign_ins.get(actor.id)
                role = sign_in.role if sign_in is not None else None
                return ActorSession(session=session, actor=actor, role=role)
        return None

    def touch(self, session_id: str, *, now: str, seen_before: str) -> None:
        session = self._state.sessions.get(session_id)
        if session is not None and session.last_seen_at < seen_before:
            self._state.sessions[session_id] = session.__replace__(last_seen_at=now)

    def _revoke_where(self, wanted: str, *, by_actor: bool, now: str) -> int:
        revoked = 0
        for session_id, session in list(self._state.sessions.items()):
            key = session.actor_id if by_actor else session.token_hash
            if key == wanted and session.revoked_at is None:
                self._state.sessions[session_id] = session.__replace__(revoked_at=now)
                revoked += 1
        return revoked

    def revoke(self, token_hash: str, *, now: str) -> bool:
        return self._revoke_where(token_hash, by_actor=False, now=now) > 0

    def revoke_for_actor(self, actor_id: str, *, now: str) -> int:
        return self._revoke_where(actor_id, by_actor=True, now=now)

    def purge(self, *, now: str) -> int:
        gone = [
            session_id
            for session_id, session in self._state.sessions.items()
            if session.expires_at < now or session.revoked_at is not None
        ]
        for session_id in gone:
            del self._state.sessions[session_id]
        return len(gone)


class FakeInviteRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def by_token_hash(self, token_hash: str) -> Invitation | None:
        for invite in self._state.invites.values():
            actor = self._state.actors.get(invite.actor_id)
            if invite.token_hash == token_hash and actor is not None:
                return Invitation(invite=invite, actor=actor)
        return None

    def add(self, row: UserInvitesRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.invites:
            raise ConstraintError(f"user_invites.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.invites.values()):
            raise ConstraintError("user_invites.token_hash is unique")
        self._state.invites[row.id] = row

    def delete_unused(self, actor_id: str) -> None:
        self._state.invites = {
            invite_id: invite
            for invite_id, invite in self._state.invites.items()
            if not (invite.actor_id == actor_id and invite.used_at is None)
        }

    def mark_used(self, invite_id: str, *, now: str) -> None:
        invite = self._state.invites.get(invite_id)
        if invite is not None:
            self._state.invites[invite_id] = invite.__replace__(used_at=now)


class FakeCredentialRepository:
    def __init__(self, state: RegistryState) -> None:
        self._state = state

    def _issued(self, credential: ApiCredentialsRow) -> IssuedToken | None:
        actor = self._state.actors.get(credential.actor_id)
        if actor is None:
            return None
        owner = self._state.actors.get(credential.owner_actor_id or "")
        return IssuedToken(
            credential=credential,
            actor=actor,
            owner_name=owner.name if owner is not None else None,
        )

    def get(self, credential_id: str) -> IssuedToken | None:
        credential = self._state.credentials.get(credential_id)
        return None if credential is None else self._issued(credential)

    def by_token_hash(self, token_hash: str) -> IssuedToken | None:
        for credential in self._state.credentials.values():
            if credential.token_hash == token_hash:
                return self._issued(credential)
        return None

    def listing(self, owner_actor_id: str | None) -> list[IssuedToken]:
        newest_first = sorted(
            self._state.credentials.values(), key=lambda row: row.created_at, reverse=True
        )
        issued = [
            self._issued(credential)
            for credential in newest_first
            if owner_actor_id is None or credential.owner_actor_id == owner_actor_id
        ]
        return [token for token in issued if token is not None]

    def owner_counts(self) -> dict[str, OwnerTokens]:
        counts: dict[str, OwnerTokens] = {}
        for credential in self._state.credentials.values():
            owner = credential.owner_actor_id
            if owner is None or credential.revoked_at is not None:
                continue
            seen = counts.get(owner, OwnerTokens(live=0, last_used_at=None))
            used = [stamp for stamp in (seen.last_used_at, credential.last_used_at) if stamp]
            counts[owner] = OwnerTokens(live=seen.live + 1, last_used_at=max(used, default=None))
        return counts

    def add(self, row: ApiCredentialsRow) -> None:
        _require_actor(self._state, row.actor_id)
        if row.id in self._state.credentials:
            raise ConstraintError(f"api_credentials.id {row.id} exists")
        if any(other.token_hash == row.token_hash for other in self._state.credentials.values()):
            raise ConstraintError("api_credentials.token_hash is unique")
        self._state.credentials[row.id] = row

    def touch(self, credential_id: str, *, now: str) -> None:
        credential = self._state.credentials.get(credential_id)
        if credential is not None:
            self._state.credentials[credential_id] = credential.__replace__(last_used_at=now)

    def revoke(self, credential_id: str, *, now: str) -> bool:
        credential = self._state.credentials.get(credential_id)
        if credential is None or credential.revoked_at is not None:
            return False
        self._state.credentials[credential_id] = credential.__replace__(revoked_at=now)
        return True

    def live_actor_ids(self, owner_actor_id: str) -> list[str]:
        return [
            credential.actor_id
            for credential in self._state.credentials.values()
            if credential.owner_actor_id == owner_actor_id and credential.revoked_at is None
        ]

    def revoke_by_owner(self, owner_actor_id: str, *, now: str) -> None:
        for credential_id in [
            credential.id
            for credential in self._state.credentials.values()
            if credential.owner_actor_id == owner_actor_id and credential.revoked_at is None
        ]:
            self.revoke(credential_id, now=now)


class FakeRegistryRepositories:
    def __init__(self, state: RegistryState) -> None:
        # Typed as the Protocols: pyright proves each fake implements its repository here.
        self.actors: ActorRepository = FakeActorRepository(state)
        self.users: UserRepository = FakeUserRepository(state)
        self.sessions: SessionRepository = FakeSessionRepository(state)
        self.invites: InviteRepository = FakeInviteRepository(state)
        self.credentials: CredentialRepository = FakeCredentialRepository(state)


class FakeRegistryUnitOfWork:
    """Commits a writer that ends normally, rolls back one that raises; a reader never commits."""

    def __init__(self, state: RegistryState) -> None:
        self.state = state
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def reader(self) -> Generator[FakeRegistryRepositories]:
        snapshot = self.state.snapshot()
        try:
            yield FakeRegistryRepositories(self.state)
        finally:
            self.state.restore(snapshot)

    @contextmanager
    def writer(self) -> Generator[FakeRegistryRepositories]:
        snapshot = self.state.snapshot()
        try:
            yield FakeRegistryRepositories(self.state)
        except BaseException:
            self.state.restore(snapshot)
            self.rollbacks += 1
            raise
        self.commits += 1


def registry_unit_of_work(state: RegistryState) -> RegistryUnitOfWork:
    """The fake as the Protocol a service takes; pyright proves the contract."""
    return FakeRegistryUnitOfWork(state)
