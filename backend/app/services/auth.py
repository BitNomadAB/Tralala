from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.config import Settings
from ..core.context import (
    MEMBER_TOKEN_SCOPES,
    ROLE_ADMIN,
    ROLES,
    ActorContext,
    scopes_for_role,
)
from ..core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailure
from ..core.security import (
    create_session_value,
    generate_token,
    hash_password,
    hash_token,
    new_csrf_token,
    new_session_id,
    read_session_value,
    resolve_secret_key,
    verify_password,
)
from ..schemas.auth import CredentialCreate, PreferencesUpdate
from ..storage.registry import Registry
from ..storage.sqlite import utcnow

# Verified even when the user does not exist so both paths spend the same hashing work.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")

# Reused placeholder passwords and a few obvious choices; the length rule does most of the work.
WEAK_PASSWORDS = frozenset(
    {"admin", "password", "changeme", "change-me", "secret", "letmein", "qwerty", "12345678"}
)


def _iso_after(seconds: int) -> str:
    moment = datetime.now(UTC) + timedelta(seconds=seconds)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token_scopes() -> frozenset[str]:
    """Scopes an API token may hold; administration scopes stay with user accounts."""
    from ..core.context import SCOPES

    blocked = {"credentials:admin", "users:admin"}
    return frozenset(scope for scope in SCOPES if scope not in blocked)


class AuthService:
    def __init__(self, settings: Settings, registry: Registry) -> None:
        self.settings = settings
        self.registry = registry
        self.secret_key = resolve_secret_key(settings)

    # --- sessions --------------------------------------------------------------

    def login(self, username: str, password: str) -> dict[str, Any]:
        record = self.registry.user_by_name(username)
        stored = record["password_hash"] if record else _DUMMY_PASSWORD_HASH
        valid = verify_password(password, stored)
        if record is None or not valid:
            raise Unauthorized("Invalid credentials", code="invalid_credentials")
        session_id = new_session_id()
        value, _expires_epoch = create_session_value(
            self.secret_key, session_id, self.settings.session_ttl_seconds
        )
        expires_at = _iso_after(self.settings.session_ttl_seconds)
        self.registry.create_session(
            token_hash=hash_token(session_id),
            actor_id=record["id"],
            expires_at=expires_at,
        )
        scopes = scopes_for_role(record["role"])
        return {
            "actor": {
                "id": record["id"],
                "type": record["type"],
                "name": record["name"],
                "role": record["role"],
                "scopes": sorted(scopes),
                "preferences": self._preferences(record["id"]),
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
        return self.registry.revoke_session(hash_token(parsed[0]))

    def actor_from_session(self, session_value: str) -> ActorContext:
        parsed = read_session_value(self.secret_key, session_value)
        if parsed is None:
            raise Unauthorized("Session expired or invalid", code="invalid_session")
        session_id, _expires = parsed
        record = self.registry.session_by_hash(hash_token(session_id))
        if (
            record is None
            or record["revoked_at"] is not None
            or record["disabled_at"] is not None
            or record["expires_at"] < utcnow()
        ):
            raise Unauthorized("Session expired or invalid", code="invalid_session")
        self.registry.touch_session(record["id"])
        return ActorContext(
            actor_id=record["actor_id"],
            actor_type=record["actor_type"],
            actor_name=record["actor_name"],
            scopes=scopes_for_role(record["role"]),
            role=record["role"],
        )

    def actor_from_token(self, token: str) -> ActorContext:
        credential = self.registry.credential_by_token_hash(hash_token(token))
        if credential is None:
            raise Unauthorized("Invalid API token", code="invalid_token")
        if credential["revoked_at"] is not None or credential["disabled_at"] is not None:
            raise Unauthorized("API token revoked", code="token_revoked")
        if credential["expires_at"] and credential["expires_at"] < utcnow():
            raise Unauthorized("API token expired", code="token_expired")
        try:
            scopes = frozenset(json.loads(credential["scopes"]))
        except (TypeError, ValueError):
            scopes = frozenset()
        self.registry.touch_credential(credential["id"])
        return ActorContext(
            actor_id=credential["actor_id"],
            actor_type=credential["actor_type"],
            actor_name=credential["actor_name"],
            scopes=scopes,
        )

    # --- accounts --------------------------------------------------------------

    def _preferences(self, actor_id: str) -> dict[str, Any]:
        row = self.registry.user_preferences(actor_id)
        return {
            "theme_mode": row.get("theme_mode"),
            "theme_kit": row.get("theme_kit"),
        }

    def preferences(self, actor: ActorContext) -> dict[str, Any]:
        """Per-account appearance. Agents and tokens have no personal preferences."""
        if not actor.is_user:
            return {"theme_mode": None, "theme_kit": None}
        return self._preferences(actor.actor_id)

    def update_preferences(
        self, actor: ActorContext, payload: PreferencesUpdate
    ) -> dict[str, Any]:
        if not actor.is_user:
            raise Forbidden("Appearance preferences belong to a signed-in account")
        current = self._preferences(actor.actor_id)
        changes = payload.model_dump(exclude_unset=True)
        merged = {**current, **changes}
        self.registry.set_user_preferences(
            actor.actor_id,
            theme_mode=merged["theme_mode"],
            theme_kit=merged["theme_kit"],
        )
        return self._preferences(actor.actor_id)

    def validate_password(self, password: str, *, username: str | None = None) -> None:
        minimum = max(8, int(self.settings.password_min_length))
        if len(password) < minimum:
            raise ValidationFailure(
                f"Password must be at least {minimum} characters",
                details={"minimum_length": minimum},
            )
        if password.strip().lower() in WEAK_PASSWORDS:
            raise ValidationFailure("Choose a stronger password")
        if username and password.strip().casefold() == username.strip().casefold():
            raise ValidationFailure("Password must not be the username")

    def change_password(
        self, actor: ActorContext, current_password: str, new_password: str
    ) -> dict[str, Any]:
        if not actor.is_user:
            raise Unauthorized("Only a user session can change a password")
        record = self.registry.user_by_id(actor.actor_id)
        if record is None:
            raise Unauthorized("Account not found")
        if not verify_password(current_password, record["password_hash"]):
            raise Unauthorized("Current password is incorrect", code="invalid_credentials")
        self.validate_password(new_password, username=record["name"])
        self.registry.set_user_password(actor.actor_id, hash_password(new_password))
        revoked = self.registry.revoke_actor_sessions(actor.actor_id)
        return {"changed": True, "revoked_sessions": revoked}

    def list_users(self, actor: ActorContext) -> list[dict[str, Any]]:
        """Accounts with how many live agent accesses each one holds."""
        actor.require("users:admin")
        counts = self.registry.credential_owner_counts()
        users = self.registry.list_users()
        for user in users:
            user["disabled"] = user["disabled_at"] is not None
            entry = counts.get(str(user["id"])) or {}
            user["agent_access_count"] = int(entry.get("live") or 0)
            user["agent_access_last_used_at"] = entry.get("last_used_at")
        return users

    def create_user(
        self, actor: ActorContext, *, name: str, password: str, role: str
    ) -> dict[str, Any]:
        actor.require("users:admin")
        if role not in ROLES:
            raise ValidationFailure("Unknown role", details={"allowed": list(ROLES)})
        self.validate_password(password, username=name)
        if self.registry.user_by_name(name) is not None:
            raise Conflict("A user with this name already exists", details={"name": name})
        user = self.registry.create_user(
            name=name, password_hash=hash_password(password), role=role
        )
        user["disabled"] = False
        return user

    def update_user(
        self, actor: ActorContext, user_id: str, *, role: str | None, disabled: bool | None
    ) -> dict[str, Any]:
        actor.require("users:admin")
        record = self.registry.user_by_id(user_id)
        if record is None:
            raise NotFound("User not found")
        if role is not None and role not in ROLES:
            raise ValidationFailure("Unknown role", details={"allowed": list(ROLES)})
        losing_admin = (role is not None and role != ROLE_ADMIN) or (disabled is True)
        if losing_admin and self.registry.count_admins(exclude=user_id) == 0:
            raise Conflict("At least one enabled administrator must remain")
        if role is not None:
            self.registry.set_user_role(user_id, role)
            self.registry.revoke_actor_sessions(user_id)
        if disabled is True:
            self.registry.disable_actor(user_id)
            self.registry.revoke_actor_sessions(user_id)
            # A person's agent access is an extension of their account: disabling the account must
            # stop every agent acting on its behalf, or the disable is only half a switch.
            self.registry.revoke_credentials_by_owner(user_id)
        elif disabled is False:
            self.registry.enable_actor(user_id)
        updated = self.registry.user_by_id(user_id)
        if updated is None:
            raise NotFound("User not found")
        counts = self.registry.credential_owner_counts().get(str(user_id)) or {}
        return {
            "id": updated["id"],
            "name": updated["name"],
            "role": updated["role"],
            "created_at": updated["created_at"],
            "disabled": updated["disabled_at"] is not None,
            "agent_access_count": int(counts.get("live") or 0),
            "agent_access_last_used_at": counts.get("last_used_at"),
        }

    def reset_password(
        self, actor: ActorContext, user_id: str, new_password: str
    ) -> dict[str, Any]:
        actor.require("users:admin")
        record = self.registry.user_by_id(user_id)
        if record is None:
            raise NotFound("User not found")
        self.validate_password(new_password, username=record["name"])
        self.registry.set_user_password(user_id, hash_password(new_password))
        revoked = self.registry.revoke_actor_sessions(user_id)
        return {"id": user_id, "revoked_sessions": revoked}

    # --- enrolment invites -----------------------------------------------------

    def create_invite(
        self, actor: ActorContext, user_id: str, *, expires_in_hours: int | None = None
    ) -> dict[str, Any]:
        """Issue a one-time enrolment link. The token is returned once and stored hashed."""
        actor.require("users:admin")
        record = self.registry.user_by_id(user_id)
        if record is None:
            raise NotFound("User not found")
        if record["disabled_at"] is not None:
            raise Conflict("A disabled account cannot be invited", code="user_disabled")
        hours = int(expires_in_hours or self.settings.invite_ttl_hours)
        token = generate_token()
        invite = self.registry.create_invite(
            actor_id=user_id,
            token_hash=hash_token(token),
            created_by_actor_id=actor.actor_id,
            expires_at=_iso_after(hours * 60 * 60),
        )
        return {
            "user_id": user_id,
            "user_name": record["name"],
            "token": token,
            "path": f"/enrol?token={token}",
            "expires_at": invite["expires_at"],
        }

    def accept_invite(self, token: str, password: str) -> dict[str, Any]:
        """Set the password from a valid invite, mark it used and sign the person in."""
        record = self.registry.invite_by_token_hash(hash_token(token))
        if record is None:
            raise Unauthorized("This invitation link is not valid", code="invite_invalid")
        if record["used_at"] is not None:
            raise Unauthorized("This invitation link was already used", code="invite_used")
        if record["expires_at"] < utcnow():
            raise Unauthorized("This invitation link has expired", code="invite_expired")
        if record["disabled_at"] is not None:
            raise Unauthorized("This account is disabled", code="user_disabled")
        self.validate_password(password, username=record["name"])
        self.registry.set_user_password(record["actor_id"], hash_password(password))
        self.registry.mark_invite_used(record["id"])
        self.registry.revoke_actor_sessions(record["actor_id"])
        return self.login(record["name"], password)

    # --- API credentials -------------------------------------------------------

    def _credential_expiry(self, expires_in_days: int | None) -> str | None:
        if expires_in_days is None:
            days = int(self.settings.credential_default_ttl_days)
        else:
            days = expires_in_days
        if days <= 0:
            return None
        return _iso_after(days * 24 * 60 * 60)

    def _issue(
        self,
        actor: ActorContext,
        payload: CredentialCreate,
        *,
        owner_actor_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        unknown = [scope for scope in payload.scopes if scope not in _token_scopes()]
        if unknown:
            raise ValidationFailure("Unknown scope requested", details={"unknown_scopes": unknown})
        agent = self.registry.create_actor(type_="agent", name=payload.name)
        token = generate_token()
        credential = self.registry.create_credential(
            actor_id=agent["id"],
            owner_actor_id=owner_actor_id if owner_actor_id is not None else actor.actor_id,
            name=payload.name,
            token_hash=hash_token(token),
            scopes=payload.scopes,
            expires_at=(
                expires_at
                if expires_at is not None
                else self._credential_expiry(payload.expires_in_days)
            ),
        )
        credential["actor_name"] = agent["name"]
        credential["owner_name"] = actor.actor_name
        credential["token"] = token
        return credential

    def _member_policy(self, actor: ActorContext, payload: CredentialCreate) -> int:
        """A person's own agent access: within the member vocabulary, capped and time-boxed."""
        outside = [scope for scope in payload.scopes if scope not in MEMBER_TOKEN_SCOPES]
        if outside:
            raise ValidationFailure(
                "A personal agent access cannot hold these scopes; ask an administrator for a "
                "wider token",
                code="forbidden_scope",
                details={"outside": outside, "allowed": list(MEMBER_TOKEN_SCOPES)},
            )
        live = len(
            [
                entry
                for entry in self.registry.list_credentials(owner_actor_id=actor.actor_id)
                if entry["revoked_at"] is None
            ]
        )
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

    def create_credential(self, actor: ActorContext, payload: CredentialCreate) -> dict[str, Any]:
        """Any signed-in person may issue an agent access; only an admin may issue a wide one."""
        if actor.is_admin:
            return self._issue(actor, payload)
        days = self._member_policy(actor, payload)
        return self._issue(
            actor,
            payload,
            owner_actor_id=actor.actor_id,
            expires_at=_iso_after(days * 24 * 60 * 60),
        )

    def _owned_or_admin(self, actor: ActorContext, credential_id: str) -> dict[str, Any]:
        credential = self.registry.credential(credential_id)
        if credential is None or credential["revoked_at"] is not None:
            raise NotFound("Credential not found or already revoked")
        if not actor.is_admin and credential.get("owner_actor_id") != actor.actor_id:
            # A member must not learn whether somebody else's token exists.
            raise NotFound("Credential not found or already revoked")
        return credential

    def rotate_credential(self, actor: ActorContext, credential_id: str) -> dict[str, Any]:
        existing = self._owned_or_admin(actor, credential_id)
        scopes = json.loads(existing["scopes"])
        name = f"{str(existing['name'])[:180]} (rotated)"
        owner = existing.get("owner_actor_id")
        if actor.is_admin:
            issued = self._issue(
                actor,
                CredentialCreate(name=name, scopes=scopes, expires_in_days=None),
                owner_actor_id=owner,
            )
        else:
            days = self._member_policy(
                actor, CredentialCreate(name=name, scopes=scopes, expires_in_days=None)
            )
            issued = self._issue(
                actor,
                CredentialCreate(name=name, scopes=scopes, expires_in_days=None),
                owner_actor_id=actor.actor_id,
                expires_at=_iso_after(int(days or 1) * 24 * 60 * 60),
            )
        self.revoke_credential(actor, credential_id)
        return issued

    def list_credentials(
        self, actor: ActorContext, *, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        """The caller's own agent access, or every token when an administrator asks."""
        if actor.is_admin:
            return self.registry.list_credentials(owner_actor_id=owner_id)
        return self.registry.list_credentials(owner_actor_id=actor.actor_id)

    def revoke_credential(self, actor: ActorContext, credential_id: str) -> bool:
        credential = self._owned_or_admin(actor, credential_id)
        revoked = self.registry.revoke_credential(credential_id)
        if revoked:
            self.registry.disable_actor(credential["actor_id"])
        return revoked
