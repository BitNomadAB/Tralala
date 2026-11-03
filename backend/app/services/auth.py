"""Accounts, sessions, enrolment invitations and API tokens.

The service reaches the registry only through the account repositories and the registry unit of
work (``app/repositories``). The clock, the id source and the password hashing are passed in, with
the real ones as defaults, so every rule here runs in a unit test without a database or the cost of
scrypt; tokens, session ids and CSRF values always come from ``core.security``. Each operation reads
what it needs, hashes outside any transaction, and then writes in one writer, so a change that
touches several rows (disabling a person and everything they issued) commits as a whole.
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, TypeIs
from uuid import uuid4

from ..core.config import Settings
from ..core.context import (
    MEMBER_TOKEN_SCOPES,
    ROLE_ADMIN,
    ROLES,
    SCOPES,
    ActorContext,
    scopes_for_role,
)
from ..core.dates import iso_utc
from ..core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailure
from ..core.security import (
    BOOTSTRAP_PASSWORD_FILE_NAME,
    INSECURE_BOOTSTRAP_PASSWORDS,
    create_session_value,
    generate_token,
    hash_password,
    hash_token,
    new_csrf_token,
    new_session_id,
    read_session_value,
    resolve_secret_key,
    verify_password,
    write_private_file,
)
from ..db.generated.registry import (
    ActorsRow,
    ApiCredentialsRow,
    SessionsRow,
    UserCredentialsRow,
    UserInvitesRow,
)
from ..repositories.accounts import IssuedToken
from ..repositories.registry import RegistryRepositories, RegistryUnitOfWork
from ..schemas.auth import CredentialCreate, PreferencesUpdate

# The first administrator's warning keeps the logger operators have always seen it under.
logger = logging.getLogger("tralala.registry")

# Verified even when the user does not exist so both paths spend the same hashing work.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")

# Reused placeholder passwords and a few obvious choices; the length rule does most of the work.
WEAK_PASSWORDS = frozenset(
    {"admin", "password", "changeme", "change-me", "secret", "letmein", "qwerty", "12345678"}
)

# A session is marked as seen at most this often, so a busy client does not write on every call.
SESSION_TOUCH_INTERVAL_SECONDS = 300

_DAY = 24 * 60 * 60
_HOUR = 60 * 60


class Preferences(TypedDict):
    theme_mode: str | None
    theme_kit: str | None


class SignedInActor(TypedDict):
    id: str
    type: str
    name: str
    role: str
    scopes: list[str]
    preferences: Preferences


class SignIn(TypedDict):
    """A new session: the cookie value, its expiry and the CSRF value the client repeats."""

    actor: SignedInActor
    session: str
    expires_at: str
    csrf_token: str


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


class CredentialEntry(TypedDict):
    """An API token as listed: never the token, never its hash."""

    id: str
    actor_id: str
    owner_actor_id: str | None
    actor_name: str
    owner_name: str | None
    name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    revoked_at: str | None


class CredentialIssued(TypedDict):
    """A new API token: the one time ``token`` is returned; only its hash is stored."""

    id: str
    actor_id: str
    owner_actor_id: str | None
    name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None
    revoked_at: str | None
    last_used_at: str | None
    actor_name: str
    owner_name: str
    token: str


def _token_scopes() -> frozenset[str]:
    """Scopes an API token may hold; administration scopes stay with user accounts."""
    blocked = {"credentials:admin", "users:admin"}
    return frozenset(scope for scope in SCOPES if scope not in blocked)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def stored_scopes(raw: str) -> list[str]:
    """The scopes a token row holds: the names in its JSON list; anything else holds none."""
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        return []
    if not _is_list(parsed):
        return []
    return [scope for scope in parsed if isinstance(scope, str)]


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


def _preferences(record: UserCredentialsRow | None) -> Preferences:
    if record is None:
        return {"theme_mode": None, "theme_kit": None}
    return {"theme_mode": record.theme_mode, "theme_kit": record.theme_kit}


def _credential_entry(token: IssuedToken) -> CredentialEntry:
    credential = token.credential
    return {
        "id": credential.id,
        "actor_id": credential.actor_id,
        "owner_actor_id": credential.owner_actor_id,
        "actor_name": token.actor.name,
        "owner_name": token.owner_name,
        "name": credential.name,
        "scopes": stored_scopes(credential.scopes),
        "created_at": credential.created_at,
        "expires_at": credential.expires_at,
        "last_used_at": credential.last_used_at,
        "revoked_at": credential.revoked_at,
    }


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
        with self.store.reader() as repos:
            user = repos.users.enabled_by_name(username)
        stored = user.credentials.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        valid = self._verify_password(password, stored)
        if user is None or not valid:
            raise Unauthorized("Invalid credentials", code="invalid_credentials")
        session_id = new_session_id()
        value, _expires_epoch = create_session_value(
            self.secret_key, session_id, self.settings.session_ttl_seconds
        )
        moment = self._clock()
        now = iso_utc(moment)
        expires_at = iso_utc(moment + timedelta(seconds=self.settings.session_ttl_seconds))
        with self.store.writer() as repos:
            repos.sessions.add(
                SessionsRow(
                    id=self._new_id(),
                    token_hash=hash_token(session_id),
                    actor_id=user.actor.id,
                    created_at=now,
                    expires_at=expires_at,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )
        role = user.credentials.role
        return {
            "actor": {
                "id": user.actor.id,
                "type": user.actor.type,
                "name": user.actor.name,
                "role": role,
                "scopes": sorted(scopes_for_role(role)),
                "preferences": _preferences(user.credentials),
            },
            "session": value,
            "expires_at": expires_at,
            "csrf_token": new_csrf_token(),
        }

    def logout(self, session_value: str | None) -> bool:
        if not session_value:
            return False
        parsed = read_session_value(self.secret_key, session_value)
        if parsed is None:
            return False
        with self.store.writer() as repos:
            return repos.sessions.revoke(hash_token(parsed[0]), now=self._stamp())

    def actor_from_session(self, session_value: str) -> ActorContext:
        parsed = read_session_value(self.secret_key, session_value)
        if parsed is None:
            raise Unauthorized("Session expired or invalid", code="invalid_session")
        session_id, _expires = parsed
        with self.store.reader() as repos:
            found = repos.sessions.by_token_hash(hash_token(session_id))
        moment = self._clock()
        now = iso_utc(moment)
        if (
            found is None
            or found.session.revoked_at is not None
            or found.actor.disabled_at is not None
            or found.session.expires_at < now
        ):
            raise Unauthorized("Session expired or invalid", code="invalid_session")
        seen_before = iso_utc(moment - timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS))
        with self.store.writer() as repos:
            repos.sessions.touch(found.session.id, now=now, seen_before=seen_before)
        return ActorContext(
            actor_id=found.session.actor_id,
            actor_type=found.actor.type,
            actor_name=found.actor.name,
            scopes=scopes_for_role(found.role),
            role=found.role,
        )

    def actor_from_token(self, token: str) -> ActorContext:
        with self.store.reader() as repos:
            found = repos.credentials.by_token_hash(hash_token(token))
        if found is None:
            raise Unauthorized("Invalid API token", code="invalid_token")
        credential = found.credential
        if credential.revoked_at is not None or found.actor.disabled_at is not None:
            raise Unauthorized("API token revoked", code="token_revoked")
        now = self._stamp()
        if credential.expires_at and credential.expires_at < now:
            raise Unauthorized("API token expired", code="token_expired")
        scopes = frozenset(stored_scopes(credential.scopes))
        with self.store.writer() as repos:
            repos.credentials.touch(credential.id, now=now)
        return ActorContext(
            actor_id=credential.actor_id,
            actor_type=found.actor.type,
            actor_name=found.actor.name,
            scopes=scopes,
        )

    # --- accounts ------------------------------------------------------------------------------

    def preferences(self, actor: ActorContext) -> Preferences:
        """Per-account appearance. Agents and tokens have no personal preferences."""
        if not actor.is_user:
            return {"theme_mode": None, "theme_kit": None}
        with self.store.reader() as repos:
            return _preferences(repos.users.credentials(actor.actor_id))

    def update_preferences(self, actor: ActorContext, payload: PreferencesUpdate) -> Preferences:
        """Change only the fields the request sent; a field sent as null clears it."""
        if not actor.is_user:
            raise Forbidden("Appearance preferences belong to a signed-in account")
        sent = payload.model_fields_set
        with self.store.writer() as repos:
            current = _preferences(repos.users.credentials(actor.actor_id))
            repos.users.set_preferences(
                actor.actor_id,
                theme_mode=payload.theme_mode if "theme_mode" in sent else current["theme_mode"],
                theme_kit=payload.theme_kit if "theme_kit" in sent else current["theme_kit"],
                now=self._stamp(),
            )
            return _preferences(repos.users.credentials(actor.actor_id))

    def validate_password(self, password: str, *, username: str | None = None) -> None:
        check_password(
            password, minimum_length=self.settings.password_min_length, username=username
        )

    def change_password(
        self, actor: ActorContext, current_password: str, new_password: str
    ) -> PasswordChanged:
        if not actor.is_user:
            raise Unauthorized("Only a user session can change a password")
        with self.store.reader() as repos:
            user = repos.users.get(actor.actor_id)
        if user is None:
            raise Unauthorized("Account not found")
        if not self._verify_password(current_password, user.credentials.password_hash):
            raise Unauthorized("Current password is incorrect", code="invalid_credentials")
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

    def _credential_expiry(self, expires_in_days: int | None) -> str | None:
        days = (
            int(self.settings.credential_default_ttl_days)
            if expires_in_days is None
            else expires_in_days
        )
        if days <= 0:
            return None
        return self._stamp(days * _DAY)

    def _issue(
        self,
        actor: ActorContext,
        payload: CredentialCreate,
        *,
        owner_actor_id: str | None = None,
        expires_at: str | None = None,
    ) -> CredentialIssued:
        allowed = _token_scopes()
        unknown: list[str] = [scope for scope in payload.scopes if scope not in allowed]
        if unknown:
            raise ValidationFailure("Unknown scope requested", details={"unknown_scopes": unknown})
        scopes: list[str] = list(payload.scopes)
        token = generate_token()
        now = self._stamp()
        agent = ActorsRow(
            id=self._new_id(), type="agent", name=payload.name, created_at=now, disabled_at=None
        )
        credential = ApiCredentialsRow(
            id=self._new_id(),
            actor_id=agent.id,
            owner_actor_id=owner_actor_id if owner_actor_id is not None else actor.actor_id,
            name=payload.name,
            token_hash=hash_token(token),
            scopes=json.dumps(scopes),
            created_at=now,
            expires_at=(
                expires_at
                if expires_at is not None
                else self._credential_expiry(payload.expires_in_days)
            ),
            last_used_at=None,
            revoked_at=None,
        )
        with self.store.writer() as repos:
            repos.actors.add(agent)
            repos.credentials.add(credential)
        return {
            "id": credential.id,
            "actor_id": credential.actor_id,
            "owner_actor_id": credential.owner_actor_id,
            "name": credential.name,
            "scopes": scopes,
            "created_at": credential.created_at,
            "expires_at": credential.expires_at,
            "revoked_at": None,
            "last_used_at": None,
            "actor_name": agent.name,
            # The issuer's name, also when an administrator issues a token another person owns.
            "owner_name": actor.actor_name,
            "token": token,
        }

    def _member_policy(self, actor: ActorContext, payload: CredentialCreate) -> int:
        """A person's own agent access: within the member vocabulary, capped and time-boxed."""
        outside: list[str] = [
            scope for scope in payload.scopes if scope not in MEMBER_TOKEN_SCOPES
        ]
        if outside:
            raise ValidationFailure(
                "A personal agent access cannot hold these scopes; ask an administrator for a "
                "wider token",
                code="forbidden_scope",
                details={"outside": outside, "allowed": list(MEMBER_TOKEN_SCOPES)},
            )
        with self.store.reader() as repos:
            owned = repos.credentials.owner_counts().get(actor.actor_id)
        live = owned.live if owned is not None else 0
        limit = int(self.settings.member_token_limit)
        if live >= limit:
            raise Conflict(
                f"You already have {live} agent accesses; revoke one before creating another",
                code="agent_access_limit",
                details={"limit": limit, "live": live},
            )
        if payload.expires_in_days is not None and payload.expires_in_days <= 0:
            raise ValidationFailure(
                "A personal agent access needs an expiry date",
                code="expiry_required",
                details={"max_days": int(self.settings.member_token_max_days)},
            )
        days = (
            int(payload.expires_in_days)
            if payload.expires_in_days is not None
            else int(self.settings.member_token_default_days)
        )
        return min(days, int(self.settings.member_token_max_days))

    def create_credential(
        self, actor: ActorContext, payload: CredentialCreate
    ) -> CredentialIssued:
        """Any signed-in person may issue an agent access; only an admin may issue a wide one."""
        if actor.is_admin:
            return self._issue(actor, payload)
        days = self._member_policy(actor, payload)
        return self._issue(
            actor, payload, owner_actor_id=actor.actor_id, expires_at=self._stamp(days * _DAY)
        )

    @staticmethod
    def _owned_or_admin(
        repos: RegistryRepositories, actor: ActorContext, credential_id: str
    ) -> IssuedToken:
        found = repos.credentials.get(credential_id)
        if found is None or found.credential.revoked_at is not None:
            raise NotFound("Credential not found or already revoked")
        if not actor.is_admin and found.credential.owner_actor_id != actor.actor_id:
            # A member must not learn whether somebody else's token exists.
            raise NotFound("Credential not found or already revoked")
        return found

    def rotate_credential(self, actor: ActorContext, credential_id: str) -> CredentialIssued:
        with self.store.reader() as repos:
            existing = self._owned_or_admin(repos, actor, credential_id).credential
        replacement = CredentialCreate.model_validate(
            {
                "name": f"{existing.name[:180]} (rotated)",
                "scopes": stored_scopes(existing.scopes),
                "expires_in_days": None,
            }
        )
        if actor.is_admin:
            issued = self._issue(actor, replacement, owner_actor_id=existing.owner_actor_id)
        else:
            days = self._member_policy(actor, replacement)
            issued = self._issue(
                actor,
                replacement,
                owner_actor_id=actor.actor_id,
                expires_at=self._stamp(int(days or 1) * _DAY),
            )
        self.revoke_credential(actor, credential_id)
        return issued

    def list_credentials(
        self, actor: ActorContext, *, owner_id: str | None = None
    ) -> list[CredentialEntry]:
        """The caller's own agent access, or every token when an administrator asks."""
        owner = (owner_id or None) if actor.is_admin else actor.actor_id
        with self.store.reader() as repos:
            tokens = repos.credentials.listing(owner)
        return [_credential_entry(token) for token in tokens]

    def revoke_credential(self, actor: ActorContext, credential_id: str) -> bool:
        """Revoke the token and disable the agent actor it acted as."""
        with self.store.writer() as repos:
            found = self._owned_or_admin(repos, actor, credential_id)
            now = self._stamp()
            revoked = repos.credentials.revoke(credential_id, now=now)
            if revoked:
                repos.actors.disable(found.credential.actor_id, now=now)
        return revoked
