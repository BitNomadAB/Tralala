"""API tokens: authenticating one, and issuing, rotating, listing and revoking them.

A token is returned once and stored only as its hash; its scopes are a JSON list on the row. An
administrator may issue any grantable scope; a member issues personal agent access within
``MEMBER_TOKEN_SCOPES``, capped and time-boxed. ``AuthService`` (``services.auth``) delegates here
with its registry unit of work, settings, clock and id source, and re-exports the types.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, TypedDict, TypeIs

from ..core.config import Settings
from ..core.context import MEMBER_TOKEN_SCOPES, SCOPES, ActorContext
from ..core.errors import Conflict, NotFound, Unauthorized, ValidationFailure
from ..core.security import generate_token, hash_token
from ..db.generated.registry import ActorsRow, ApiCredentialsRow
from ..repositories.accounts import IssuedToken
from ..repositories.registry import RegistryRepositories, RegistryUnitOfWork
from ..schemas.auth import CredentialCreate

_DAY = 24 * 60 * 60


class Stamp(Protocol):
    """Now, or ``seconds`` from now, as the registry stores time (``AuthService._stamp``)."""

    def __call__(self, seconds: int = 0) -> str: ...


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


class KeyIdentity(TypedDict):
    """The key a request authenticated with, as its own holder may see it: never the token, never
    its hash, and nothing about any other key."""

    id: str
    name: str
    issued_by: str | None
    created_at: str
    expires_at: str | None
    days_left: int | None
    expires_soon: bool
    last_used_at: str | None


EXPIRES_SOON_DAYS = 7
"""A key with fewer whole days left than this is reported as expiring soon."""


def current_key(
    store: RegistryUnitOfWork, actor: ActorContext, *, now: datetime
) -> KeyIdentity | None:
    """The key ``actor`` authenticated with; None for a session cookie or a key that is gone."""
    if actor.credential_id is None:
        return None
    with store.reader() as repos:
        found = repos.credentials.get(actor.credential_id)
    if found is None:
        return None
    credential = found.credential
    days_left: int | None = None
    if credential.expires_at:
        remaining = datetime.fromisoformat(credential.expires_at) - now
        days_left = max(0, remaining.days)
    return {
        "id": credential.id,
        "name": credential.name,
        "issued_by": found.owner_name,
        "created_at": credential.created_at,
        "expires_at": credential.expires_at,
        "days_left": days_left,
        "expires_soon": days_left is not None and days_left < EXPIRES_SOON_DAYS,
        "last_used_at": credential.last_used_at,
    }


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


def token_scopes() -> frozenset[str]:
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


def actor_from_token(store: RegistryUnitOfWork, token: str, *, stamp: Stamp) -> ActorContext:
    with store.reader() as repos:
        found = repos.credentials.by_token_hash(hash_token(token))
    if found is None:
        raise Unauthorized("Invalid API token", code="invalid_token")
    credential = found.credential
    if credential.revoked_at is not None or found.actor.disabled_at is not None:
        raise Unauthorized("API token revoked", code="token_revoked")
    now = stamp()
    if credential.expires_at and credential.expires_at < now:
        raise Unauthorized("API token expired", code="token_expired")
    scopes = frozenset(stored_scopes(credential.scopes))
    with store.writer() as repos:
        repos.credentials.touch(credential.id, now=now)
    return ActorContext(
        actor_id=credential.actor_id,
        actor_type=found.actor.type,
        actor_name=found.actor.name,
        scopes=scopes,
        credential_id=credential.id,
    )


def _credential_expiry(settings: Settings, stamp: Stamp, expires_in_days: int | None) -> str | None:
    days = int(settings.credential_default_ttl_days) if expires_in_days is None else expires_in_days
    if days <= 0:
        return None
    return stamp(days * _DAY)


def _issue(
    store: RegistryUnitOfWork,
    settings: Settings,
    actor: ActorContext,
    payload: CredentialCreate,
    *,
    stamp: Stamp,
    new_id: Callable[[], str],
    owner_actor_id: str | None = None,
    expires_at: str | None = None,
) -> CredentialIssued:
    allowed = token_scopes()
    unknown: list[str] = [scope for scope in payload.scopes if scope not in allowed]
    if unknown:
        raise ValidationFailure("Unknown scope requested", details={"unknown_scopes": unknown})
    scopes: list[str] = list(payload.scopes)
    token = generate_token()
    now = stamp()
    agent = ActorsRow(
        id=new_id(), type="agent", name=payload.name, created_at=now, disabled_at=None
    )
    credential = ApiCredentialsRow(
        id=new_id(),
        actor_id=agent.id,
        owner_actor_id=owner_actor_id if owner_actor_id is not None else actor.actor_id,
        name=payload.name,
        token_hash=hash_token(token),
        scopes=json.dumps(scopes),
        created_at=now,
        expires_at=(
            expires_at
            if expires_at is not None
            else _credential_expiry(settings, stamp, payload.expires_in_days)
        ),
        last_used_at=None,
        revoked_at=None,
    )
    with store.writer() as repos:
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


def _member_policy(
    store: RegistryUnitOfWork, settings: Settings, actor: ActorContext, payload: CredentialCreate
) -> int:
    """A person's own agent access: within the member vocabulary, capped and time-boxed."""
    outside: list[str] = [scope for scope in payload.scopes if scope not in MEMBER_TOKEN_SCOPES]
    if outside:
        raise ValidationFailure(
            "A personal agent access cannot hold these scopes; ask an administrator for a "
            "wider token",
            code="forbidden_scope",
            details={"outside": outside, "allowed": list(MEMBER_TOKEN_SCOPES)},
        )
    with store.reader() as repos:
        owned = repos.credentials.owner_counts().get(actor.actor_id)
    live = owned.live if owned is not None else 0
    limit = int(settings.member_token_limit)
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
            details={"max_days": int(settings.member_token_max_days)},
        )
    days = (
        int(payload.expires_in_days)
        if payload.expires_in_days is not None
        else int(settings.member_token_default_days)
    )
    return min(days, int(settings.member_token_max_days))


def create_credential(
    store: RegistryUnitOfWork,
    settings: Settings,
    actor: ActorContext,
    payload: CredentialCreate,
    *,
    stamp: Stamp,
    new_id: Callable[[], str],
) -> CredentialIssued:
    """A person issues an agent access, never a token; an admin may issue a wide one."""
    actor.require_human("Issuing agent access")
    if actor.is_admin:
        return _issue(store, settings, actor, payload, stamp=stamp, new_id=new_id)
    days = _member_policy(store, settings, actor, payload)
    return _issue(
        store,
        settings,
        actor,
        payload,
        stamp=stamp,
        new_id=new_id,
        owner_actor_id=actor.actor_id,
        expires_at=stamp(days * _DAY),
    )


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


def rotate_credential(
    store: RegistryUnitOfWork,
    settings: Settings,
    actor: ActorContext,
    credential_id: str,
    *,
    stamp: Stamp,
    new_id: Callable[[], str],
) -> CredentialIssued:
    """Issue a replacement and revoke the old one; issuing is a person's act, never a token's."""
    actor.require_human("Rotating agent access")
    with store.reader() as repos:
        existing = _owned_or_admin(repos, actor, credential_id).credential
    replacement = CredentialCreate.model_validate(
        {
            "name": f"{existing.name[:180]} (rotated)",
            "scopes": stored_scopes(existing.scopes),
            "expires_in_days": None,
        }
    )
    if actor.is_admin:
        issued = _issue(
            store,
            settings,
            actor,
            replacement,
            stamp=stamp,
            new_id=new_id,
            owner_actor_id=existing.owner_actor_id,
        )
    else:
        days = _member_policy(store, settings, actor, replacement)
        issued = _issue(
            store,
            settings,
            actor,
            replacement,
            stamp=stamp,
            new_id=new_id,
            owner_actor_id=actor.actor_id,
            expires_at=stamp(int(days or 1) * _DAY),
        )
    revoke_credential(store, actor, credential_id, stamp=stamp)
    return issued


def list_credentials(
    store: RegistryUnitOfWork, actor: ActorContext, *, owner_id: str | None = None
) -> list[CredentialEntry]:
    """The caller's own agent access, or every token when an administrator asks."""
    owner = (owner_id or None) if actor.is_admin else actor.actor_id
    with store.reader() as repos:
        tokens = repos.credentials.listing(owner)
    return [_credential_entry(token) for token in tokens]


def revoke_credential(
    store: RegistryUnitOfWork, actor: ActorContext, credential_id: str, *, stamp: Stamp
) -> bool:
    """Revoke the token and disable the agent actor it acted as."""
    with store.writer() as repos:
        found = _owned_or_admin(repos, actor, credential_id)
        now = stamp()
        revoked = repos.credentials.revoke(credential_id, now=now)
        if revoked:
            repos.actors.disable(found.credential.actor_id, now=now)
    return revoked
