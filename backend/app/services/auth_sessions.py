"""Sign-in and sessions: a password exchanged for a signed session, and the account's appearance.

The session cookie carries a signed id and only its hash is stored; a session is marked as seen at
most every ``SESSION_TOUCH_INTERVAL_SECONDS``. An unknown name still costs a password check, so both
paths spend the same hashing work. ``AuthService`` (``services.auth``) delegates here with its
registry unit of work, settings, secret, clock, id source and password check, and re-exports the
types.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypedDict

from ..core.config import Settings
from ..core.context import ActorContext, scopes_for_role
from ..core.dates import iso_utc
from ..core.errors import Forbidden, Unauthorized
from ..core.security import (
    create_session_value,
    hash_password,
    hash_token,
    new_csrf_token,
    new_session_id,
    read_session_value,
)
from ..db.generated.registry import SessionsRow, UserCredentialsRow
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.auth import PreferencesUpdate

# Verified even when the user does not exist so both paths spend the same hashing work.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")

# A session is marked as seen at most this often, so a busy client does not write on every call.
SESSION_TOUCH_INTERVAL_SECONDS = 300


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


def _preferences(record: UserCredentialsRow | None) -> Preferences:
    if record is None:
        return {"theme_mode": None, "theme_kit": None}
    return {"theme_mode": record.theme_mode, "theme_kit": record.theme_kit}


def login(
    store: RegistryUnitOfWork,
    settings: Settings,
    secret_key: str,
    username: str,
    password: str,
    *,
    clock: Callable[[], datetime],
    new_id: Callable[[], str],
    verify_password: Callable[[str, str], bool],
) -> SignIn:
    with store.reader() as repos:
        user = repos.users.enabled_by_name(username)
    stored = user.credentials.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    valid = verify_password(password, stored)
    if user is None or not valid:
        raise Unauthorized("Invalid credentials", code="invalid_credentials")
    session_id = new_session_id()
    value, _expires_epoch = create_session_value(
        secret_key, session_id, settings.session_ttl_seconds
    )
    moment = clock()
    now = iso_utc(moment)
    expires_at = iso_utc(moment + timedelta(seconds=settings.session_ttl_seconds))
    with store.writer() as repos:
        repos.sessions.add(
            SessionsRow(
                id=new_id(),
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


def logout(
    store: RegistryUnitOfWork,
    secret_key: str,
    session_value: str | None,
    *,
    stamp: Callable[[], str],
) -> bool:
    if not session_value:
        return False
    parsed = read_session_value(secret_key, session_value)
    if parsed is None:
        return False
    with store.writer() as repos:
        return repos.sessions.revoke(hash_token(parsed[0]), now=stamp())


def actor_from_session(
    store: RegistryUnitOfWork,
    secret_key: str,
    session_value: str,
    *,
    clock: Callable[[], datetime],
) -> ActorContext:
    parsed = read_session_value(secret_key, session_value)
    if parsed is None:
        raise Unauthorized("Session expired or invalid", code="invalid_session")
    session_id, _expires = parsed
    with store.reader() as repos:
        found = repos.sessions.by_token_hash(hash_token(session_id))
    moment = clock()
    now = iso_utc(moment)
    if (
        found is None
        or found.session.revoked_at is not None
        or found.actor.disabled_at is not None
        or found.session.expires_at < now
    ):
        raise Unauthorized("Session expired or invalid", code="invalid_session")
    seen_before = iso_utc(moment - timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS))
    with store.writer() as repos:
        repos.sessions.touch(found.session.id, now=now, seen_before=seen_before)
    return ActorContext(
        actor_id=found.session.actor_id,
        actor_type=found.actor.type,
        actor_name=found.actor.name,
        scopes=scopes_for_role(found.role),
        role=found.role,
    )


def preferences(store: RegistryUnitOfWork, actor: ActorContext) -> Preferences:
    """Per-account appearance. Agents and tokens have no personal preferences."""
    if not actor.is_user:
        return {"theme_mode": None, "theme_kit": None}
    with store.reader() as repos:
        return _preferences(repos.users.credentials(actor.actor_id))


def update_preferences(
    store: RegistryUnitOfWork,
    actor: ActorContext,
    payload: PreferencesUpdate,
    *,
    stamp: Callable[[], str],
) -> Preferences:
    """Change only the fields the request sent; a field sent as null clears it."""
    if not actor.is_user:
        raise Forbidden("Appearance preferences belong to a signed-in account")
    sent = payload.model_fields_set
    with store.writer() as repos:
        current = _preferences(repos.users.credentials(actor.actor_id))
        repos.users.set_preferences(
            actor.actor_id,
            theme_mode=payload.theme_mode if "theme_mode" in sent else current["theme_mode"],
            theme_kit=payload.theme_kit if "theme_kit" in sent else current["theme_kit"],
            now=stamp(),
        )
        return _preferences(repos.users.credentials(actor.actor_id))
