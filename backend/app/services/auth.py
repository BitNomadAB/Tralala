"""Accounts, sessions, enrolment invitations and API tokens.

The service reaches the registry only through the account repositories and the registry unit of
work (``app/repositories``). The clock, the id source and the password hashing are passed in, with
the real ones as defaults, so every rule here runs in a unit test without a database or the cost of
scrypt; tokens, session ids and CSRF values always come from ``core.security``. Each operation reads
what it needs, hashes outside any transaction, and then writes in one writer, so a change that
touches several rows (disabling a person and everything they issued) commits as a whole.

This module is the public import path. ``AuthService`` keeps the first start, the accounts and the
enrolment invitations here, and delegates sign-in, sessions and appearance preferences
(``auth_sessions``) and API tokens (``auth_tokens``) to the modules beside it, whose names it
re-exports.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ROLE_ADMIN, ROLES, ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailure
from ..core.security import (
    BOOTSTRAP_PASSWORD_FILE_NAME,
    INSECURE_BOOTSTRAP_PASSWORDS,
    generate_token,
    hash_password,
    hash_token,
    resolve_secret_key,
    verify_password,
    write_private_file,
)
from ..db.generated.registry import ActorsRow, UserCredentialsRow, UserInvitesRow
from ..repositories.registry import RegistryRepositories, RegistryUnitOfWork
from ..schemas.auth import CredentialCreate, PreferencesUpdate
from . import auth_sessions, auth_tokens
from .auth_sessions import SESSION_TOUCH_INTERVAL_SECONDS, Preferences, SignedInActor, SignIn
from .auth_tokens import CredentialEntry, CredentialIssued, stored_scopes
from .auth_tokens import token_scopes as _token_scopes

# The first administrator's warning keeps the logger operators have always seen it under.
logger = logging.getLogger("tralala.registry")

# Reused placeholder passwords and a few obvious choices; the length rule does most of the work.
WEAK_PASSWORDS = frozenset(
    {"admin", "password", "changeme", "change-me", "secret", "letmein", "qwerty", "12345678"}
)

_HOUR = 60 * 60


class PasswordChanged(TypedDict):
    changed: bool
    revoked_sessions: int


class PasswordReset(TypedDict):
    id: str
    revoked_sessions: int


class UserEntry(TypedDict):
    """A person in the administration list, with the agent access they hold."""

    id: str
    name: str
    created_at: str
    disabled_at: str | None
    role: str
    updated_at: str
    disabled: bool
    agent_access_count: int
    agent_access_last_used_at: str | None


class CreatedUser(TypedDict):
    id: str
    name: str
    role: str
    created_at: str
    disabled: bool


class UpdatedUser(TypedDict):
    id: str
    name: str
    role: str
    created_at: str
    disabled: bool
    agent_access_count: int
    agent_access_last_used_at: str | None


class InviteIssued(TypedDict):
    """The one time the enrolment token is shown; only its hash is stored."""

    user_id: str
    user_name: str
    token: str
    path: str
    expires_at: str


def check_password(password: str, *, minimum_length: int, username: str | None = None) -> None:
    """The password policy: at least eight characters (or the configured minimum, if higher),
    not a well-known password and not the username."""
    minimum = max(8, int(minimum_length))
    if len(password) < minimum:
        raise ValidationFailure(
            f"Password must be at least {minimum} characters",
            details={"minimum_length": minimum},
        )
    if password.strip().lower() in WEAK_PASSWORDS:
        raise ValidationFailure("Choose a stronger password")
    if username and password.strip().casefold() == username.strip().casefold():
        raise ValidationFailure("Password must not be the username")


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class AuthService:
    def __init__(
        self,
        settings: Settings,
        store: RegistryUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
        password_hasher: Callable[[str], str] = hash_password,
        password_verifier: Callable[[str, str], bool] = verify_password,
    ) -> None:
        self.settings = settings
        self.store = store
        self.secret_key = resolve_secret_key(settings)
        self._clock = clock
        self._new_id = new_id
        self._hash_password = password_hasher
        self._verify_password = password_verifier

    def _stamp(self, seconds: int = 0) -> str:
        """Now, or ``seconds`` from now, as the registry stores time."""
        return iso_utc(self._clock() + timedelta(seconds=seconds))

    # --- first start ---------------------------------------------------------------------------

    def bootstrap_admin(self) -> None:
        """Create the first administrator when the registry has no person yet.

        A missing or published placeholder password is replaced by a generated one, written once
        to an owner-only file in the data directory.
        """
        with self.store.reader() as repos:
            if repos.actors.any_user():
                return
        password = self.settings.bootstrap_password
        generated = password.strip().lower() in INSECURE_BOOTSTRAP_PASSWORDS
        if generated:
            password = secrets.token_urlsafe(18)
        password_hash = self._hash_password(password)
        with self.store.writer() as repos:
            self._add_user(
                repos,
                name=self.settings.bootstrap_username,
                password_hash=password_hash,
                role=ROLE_ADMIN,
            )
        if generated:
            path = Path(self.settings.data_dir) / BOOTSTRAP_PASSWORD_FILE_NAME
            write_private_file(path, f"{password}\n")
            logger.warning(
                "TRALALA_BOOTSTRAP_PASSWORD was unset or a published placeholder; generated a "
                "one-time administrator password in %s (delete the file after first sign-in)",
                path,
            )

    def purge_expired_sessions(self) -> int:
        """Delete expired and revoked sessions; run at startup."""
        with self.store.writer() as repos:
            return repos.sessions.purge(now=self._stamp())

    # --- sessions ------------------------------------------------------------------------------

    def login(self, username: str, password: str) -> SignIn:
        return auth_sessions.login(
            self.store,
            self.settings,
            self.secret_key,
            username,
            password,
            clock=self._clock,
            new_id=self._new_id,
            verify_password=self._verify_password,
        )

    def logout(self, session_value: str | None) -> bool:
        return auth_sessions.logout(self.store, self.secret_key, session_value, stamp=self._stamp)

    def actor_from_session(self, session_value: str) -> ActorContext:
        return auth_sessions.actor_from_session(
            self.store, self.secret_key, session_value, clock=self._clock
        )

    def actor_from_token(self, token: str) -> ActorContext:
        return auth_tokens.actor_from_token(self.store, token, stamp=self._stamp)

    # --- accounts ------------------------------------------------------------------------------

    def preferences(self, actor: ActorContext) -> Preferences:
        """Per-account appearance. Agents and tokens have no personal preferences."""
        return auth_sessions.preferences(self.store, actor)

    def update_preferences(self, actor: ActorContext, payload: PreferencesUpdate) -> Preferences:
        """Change only the fields the request sent; a field sent as null clears it."""
        return auth_sessions.update_preferences(self.store, actor, payload, stamp=self._stamp)

    def validate_password(self, password: str, *, username: str | None = None) -> None:
        check_password(
            password, minimum_length=self.settings.password_min_length, username=username
        )

    def change_password(
        self, actor: ActorContext, current_password: str, new_password: str
    ) -> PasswordChanged:
        # 401 means the request is not authenticated, and a client signs out on it. The caller here
        # is: a token is refused as the other person-only settings refuse it, and a wrong current
        # password is a field of the request the server refuses, like a weak new one.
        if not actor.is_user:
            raise Forbidden("Only a user session can change a password")
        with self.store.reader() as repos:
            user = repos.users.get(actor.actor_id)
        if user is None:
            raise Unauthorized("Account not found")
        if not self._verify_password(current_password, user.credentials.password_hash):
            raise ValidationFailure("Current password is incorrect", code="invalid_credentials")
        self.validate_password(new_password, username=user.actor.name)
        password_hash = self._hash_password(new_password)
        with self.store.writer() as repos:
            now = self._stamp()
            repos.users.set_password(actor.actor_id, password_hash, now=now)
            revoked = repos.sessions.revoke_for_actor(actor.actor_id, now=now)
        return {"changed": True, "revoked_sessions": revoked}

    def list_users(self, actor: ActorContext) -> list[UserEntry]:
        """Accounts with how many live agent accesses each one holds."""
        actor.require("users:admin")
        with self.store.reader() as repos:
            counts = repos.credentials.owner_counts()
            users = repos.users.all()
        entries: list[UserEntry] = []
        for user in users:
            owned = counts.get(user.actor.id)
            entries.append(
                {
                    "id": user.actor.id,
                    "name": user.actor.name,
                    "created_at": user.actor.created_at,
                    "disabled_at": user.actor.disabled_at,
                    "role": user.credentials.role,
                    "updated_at": user.credentials.updated_at,
                    "disabled": user.actor.disabled_at is not None,
                    "agent_access_count": owned.live if owned is not None else 0,
                    "agent_access_last_used_at": (
                        owned.last_used_at if owned is not None else None
                    ),
                }
            )
        return entries

    def _add_user(
        self, repos: RegistryRepositories, *, name: str, password_hash: str, role: str
    ) -> ActorsRow:
        now = self._stamp()
        actor = ActorsRow(
            id=self._new_id(), type="user", name=name, created_at=now, disabled_at=None
        )
        repos.actors.add(actor)
        repos.users.add(
            UserCredentialsRow(
                actor_id=actor.id,
                password_hash=password_hash,
                updated_at=now,
                role=role,
                theme_mode=None,
                theme_kit=None,
            )
        )
        return actor

    def create_user(
        self, actor: ActorContext, *, name: str, password: str, role: str
    ) -> CreatedUser:
        actor.require("users:admin")
        if role not in ROLES:
            raise ValidationFailure("Unknown role", details={"allowed": list(ROLES)})
        self.validate_password(password, username=name)
        with self.store.reader() as repos:
            taken = repos.users.enabled_by_name(name) is not None
        if taken:
            raise Conflict("A user with this name already exists", details={"name": name})
        password_hash = self._hash_password(password)
        with self.store.writer() as repos:
            created = self._add_user(repos, name=name, password_hash=password_hash, role=role)
        return {
            "id": created.id,
            "name": name,
            "role": role,
            "created_at": created.created_at,
            "disabled": False,
        }

    def update_user(
        self, actor: ActorContext, user_id: str, *, role: str | None, disabled: bool | None
    ) -> UpdatedUser:
        actor.require("users:admin")
        with self.store.writer() as repos:
            if repos.users.get(user_id) is None:
                raise NotFound("User not found")
            if role is not None and role not in ROLES:
                raise ValidationFailure("Unknown role", details={"allowed": list(ROLES)})
            losing_admin = (role is not None and role != ROLE_ADMIN) or (disabled is True)
            if losing_admin and repos.users.count_enabled_admins(exclude=user_id) == 0:
                raise Conflict("At least one enabled administrator must remain")
            now = self._stamp()
            if role is not None:
                repos.users.set_role(user_id, role)
                repos.sessions.revoke_for_actor(user_id, now=now)
            if disabled is True:
                repos.actors.disable(user_id, now=now)
                repos.sessions.revoke_for_actor(user_id, now=now)
                # A person's agent access is an extension of their account: disabling the account
                # must stop every agent acting on its behalf, or the disable is only half a switch.
                self._revoke_issued_by(repos, user_id, now=now)
            elif disabled is False:
                repos.actors.enable(user_id)
            updated = repos.users.get(user_id)
            owned = repos.credentials.owner_counts().get(user_id)
        if updated is None:
            raise NotFound("User not found")
        return {
            "id": updated.actor.id,
            "name": updated.actor.name,
            "role": updated.credentials.role,
            "created_at": updated.actor.created_at,
            "disabled": updated.actor.disabled_at is not None,
            "agent_access_count": owned.live if owned is not None else 0,
            "agent_access_last_used_at": owned.last_used_at if owned is not None else None,
        }

    @staticmethod
    def _revoke_issued_by(repos: RegistryRepositories, owner_id: str, *, now: str) -> None:
        """Revoke every live token the person owns and disable the agent actors behind them."""
        agents = repos.credentials.live_actor_ids(owner_id)
        repos.credentials.revoke_by_owner(owner_id, now=now)
        for agent_id in agents:
            repos.actors.disable(agent_id, now=now)

    def reset_password(
        self, actor: ActorContext, user_id: str, new_password: str
    ) -> PasswordReset:
        actor.require("users:admin")
        with self.store.reader() as repos:
            user = repos.users.get(user_id)
        if user is None:
            raise NotFound("User not found")
        self.validate_password(new_password, username=user.actor.name)
        password_hash = self._hash_password(new_password)
        with self.store.writer() as repos:
            now = self._stamp()
            repos.users.set_password(user_id, password_hash, now=now)
            revoked = repos.sessions.revoke_for_actor(user_id, now=now)
        return {"id": user_id, "revoked_sessions": revoked}

    # --- enrolment invites ---------------------------------------------------------------------

    def create_invite(
        self, actor: ActorContext, user_id: str, *, expires_in_hours: int | None = None
    ) -> InviteIssued:
        """Issue a one-time enrolment link. The token is returned once and stored hashed.

        One live invitation per account: a new link replaces an unused older one.
        """
        actor.require("users:admin")
        with self.store.writer() as repos:
            user = repos.users.get(user_id)
            if user is None:
                raise NotFound("User not found")
            if user.actor.disabled_at is not None:
                raise Conflict("A disabled account cannot be invited", code="user_disabled")
            hours = int(expires_in_hours or self.settings.invite_ttl_hours)
            token = generate_token()
            invite = UserInvitesRow(
                id=self._new_id(),
                actor_id=user_id,
                token_hash=hash_token(token),
                created_by_actor_id=actor.actor_id,
                created_at=self._stamp(),
                expires_at=self._stamp(hours * _HOUR),
                used_at=None,
            )
            repos.invites.delete_unused(user_id)
            repos.invites.add(invite)
        return {
            "user_id": user_id,
            "user_name": user.actor.name,
            "token": token,
            "path": f"/enrol?token={token}",
            "expires_at": invite.expires_at,
        }

    def accept_invite(self, token: str, password: str) -> SignIn:
        """Set the password from a valid invite, mark it used and sign the person in."""
        with self.store.reader() as repos:
            found = repos.invites.by_token_hash(hash_token(token))
        if found is None:
            raise Unauthorized("This invitation link is not valid", code="invite_invalid")
        if found.invite.used_at is not None:
            raise Unauthorized("This invitation link was already used", code="invite_used")
        if found.invite.expires_at < self._stamp():
            raise Unauthorized("This invitation link has expired", code="invite_expired")
        if found.actor.disabled_at is not None:
            raise Unauthorized("This account is disabled", code="user_disabled")
        self.validate_password(password, username=found.actor.name)
        password_hash = self._hash_password(password)
        with self.store.writer() as repos:
            now = self._stamp()
            repos.users.set_password(found.actor.id, password_hash, now=now)
            repos.invites.mark_used(found.invite.id, now=now)
            repos.sessions.revoke_for_actor(found.actor.id, now=now)
        return self.login(found.actor.name, password)

    # --- API credentials -----------------------------------------------------------------------

    def create_credential(
        self, actor: ActorContext, payload: CredentialCreate
    ) -> CredentialIssued:
        """Any signed-in person may issue an agent access; only an admin may issue a wide one."""
        return auth_tokens.create_credential(
            self.store, self.settings, actor, payload, stamp=self._stamp, new_id=self._new_id
        )

    def rotate_credential(self, actor: ActorContext, credential_id: str) -> CredentialIssued:
        return auth_tokens.rotate_credential(
            self.store, self.settings, actor, credential_id, stamp=self._stamp, new_id=self._new_id
        )

    def list_credentials(
        self, actor: ActorContext, *, owner_id: str | None = None
    ) -> list[CredentialEntry]:
        """The caller's own agent access, or every token when an administrator asks."""
        return auth_tokens.list_credentials(self.store, actor, owner_id=owner_id)

    def revoke_credential(self, actor: ActorContext, credential_id: str) -> bool:
        """Revoke the token and disable the agent actor it acted as."""
        return auth_tokens.revoke_credential(self.store, actor, credential_id, stamp=self._stamp)


__all__ = [
    "SESSION_TOUCH_INTERVAL_SECONDS",
    "WEAK_PASSWORDS",
    "AuthService",
    "CreatedUser",
    "CredentialEntry",
    "CredentialIssued",
    "InviteIssued",
    "PasswordChanged",
    "PasswordReset",
    "Preferences",
    "SignIn",
    "SignedInActor",
    "UpdatedUser",
    "UserEntry",
    "_token_scopes",
    "check_password",
    "stored_scopes",
]
