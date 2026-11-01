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

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_MEMBER)

# Every signed-in person shares the same working access; account administration and the global
# API keys (installation-wide bearer tokens) stay with the admin role.
ROLE_SCOPES: dict[str, frozenset[str]] = {
    ROLE_ADMIN: frozenset(SCOPES),
    ROLE_MEMBER: frozenset(
        scope for scope in SCOPES if scope not in {"users:admin", "credentials:admin"}
    ),
}


def scopes_for_role(role: str | None) -> frozenset[str]:
    return ROLE_SCOPES.get(role or "", ROLE_SCOPES[ROLE_MEMBER])


@dataclass(slots=True)
class ActorContext:
    actor_id: str
    actor_type: str
    actor_name: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    request_id: str = ""
    role: str | None = None

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
