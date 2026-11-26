from __future__ import annotations

from dataclasses import dataclass, field

from .errors import Forbidden

# Canonical scopes.
SCOPES: tuple[str, ...] = (
    "boards:read",
    "boards:write",
    "boards:admin",
    "cards:read",
    "cards:write",
    "comments:write",
    "loops:read",
    "loops:write",
    "loops:generate",
    "loops:review",
    "loops:decide",
    "history:read",
    "agents:read",
    "agents:write",
    "agents:admin",
    "discussions:read",
    "discussions:write",
    "discussions:admin",
    "discussions:vote",
    "credentials:admin",
    "users:admin",
)

DECIDE_SCOPE = "loops:decide"
"""The right to decide in the editor: a person gives it to a key they own, and only while the
installation's setting ``editor_decisions`` is on. On its own it opens no tool and changes no
answer; every decision still asks for a person."""

# Rights that exist only on a key. A session never holds them, so ``has_scope(DECIDE_SCOPE)`` is
# true only for a request that came through a key its owner gave the right.
KEY_ONLY_SCOPES: frozenset[str] = frozenset({DECIDE_SCOPE})

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_MEMBER)

# Every signed-in person shares the same working access; account administration and the global
# API keys (installation-wide bearer tokens) stay with the admin role.
ROLE_SCOPES: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset(SCOPES) - KEY_ONLY_SCOPES,
    ROLE_MEMBER: frozenset(
        scope
        for scope in SCOPES
        if scope not in {"users:admin", "credentials:admin"} and scope not in KEY_ONLY_SCOPES
    ),
}


def scopes_for_role(role: str | None) -> frozenset[str]:
    return ROLE_SCOPES.get(role or "", ROLE_SCOPES[ROLE_MEMBER])


# What a person's own agent may hold. A member manages their own "interaction agent access", so the
# token vocabulary is limited to working the boards: structure, agents, accounts and tokens stay
# with the admin role. An admin-issued token may still hold any grantable scope.
MEMBER_TOKEN_SCOPES: tuple[str, ...] = (
    "boards:read",
    "cards:read",
    "cards:write",
    "comments:write",
    "loops:read",
    "loops:write",
    "loops:generate",
    DECIDE_SCOPE,
    "history:read",
    "discussions:read",
    "discussions:write",
)


@dataclass(slots=True)
class ActorContext:
    actor_id: str
    actor_type: str
    actor_name: str
    scopes: frozenset[str] = field(default_factory=frozenset[str])
    request_id: str = ""
    role: str | None = None
    # The API token the request authenticated with; None for a session cookie or an internal actor.
    credential_id: str | None = None

    @property
    def is_user(self) -> bool:
        return self.actor_type == "user"

    @property
    def is_admin(self) -> bool:
        return self.is_user and self.role == ROLE_ADMIN

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise Forbidden(f"Missing required scope: {scope}", details={"required_scope": scope})

    def require_human(self, action: str) -> None:
        """Human-only workflow decisions can never be satisfied by an agent credential."""
        if not self.is_user:
            raise Forbidden(
                f"{action} is a human decision",
                code="human_action_required",
                details={"action": action, "actor_type": self.actor_type},
            )
