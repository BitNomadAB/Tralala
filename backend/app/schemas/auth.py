from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .common import Name, OutModel, StrictModel

Scope = Literal[
    "boards:read",
    "boards:write",
    "boards:admin",
    "cards:read",
    "cards:write",
    "comments:write",
    "loops:read",
    "loops:write",
    "loops:generate",
    "history:read",
    "discussions:read",
    "discussions:write",
    "discussions:vote",
]
# ``loops:review`` is deliberately absent: approving plans, confirming human work and accepting QA
# always require a human session, so a token can never hold a usable review grant.
Role = Literal["admin", "member"]
ThemeMode = Literal["dark", "light", "system"]
ThemeKit = Literal["carenomad", "matchmap", "classic"]


class LoginRequest(StrictModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class PreferencesOut(OutModel):
    theme_mode: ThemeMode | None = None
    theme_kit: ThemeKit | None = None


class PreferencesUpdate(StrictModel):
    theme_mode: ThemeMode | None = None
    theme_kit: ThemeKit | None = None


class ActorOut(OutModel):
    id: str
    type: Literal["user", "agent", "service"]
    name: str
    role: str | None = None
    scopes: list[str] = Field(default_factory=list)
    preferences: PreferencesOut | None = None


class LoginResponse(OutModel):
    actor: ActorOut
    csrf_token: str


class PasswordChange(StrictModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserCreate(StrictModel):
    name: Name
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    role: Role = "member"


class UserUpdate(StrictModel):
    role: Role | None = None
    disabled: bool | None = None


class UserPasswordReset(StrictModel):
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class UserOut(OutModel):
    id: str
    name: str
    role: str
    created_at: str
    disabled: bool = False
    agent_access_count: int = 0
    agent_access_last_used_at: str | None = None


class InviteCreate(StrictModel):
    """How long the enrolment link stays valid; the default keeps it to three days."""

    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class InviteCreated(OutModel):
    user_id: str
    user_name: str
    token: str
    path: str
    expires_at: str
    warning: str = "Send this link once; it is not retrievable later."


class EnrolRequest(StrictModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class CredentialCreate(StrictModel):
    name: Name
    scopes: list[Scope] = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=0, le=3650)


class CredentialOut(OutModel):
    id: str
    actor_id: str
    actor_name: str | None = None
    owner_actor_id: str | None = None
    owner_name: str | None = None
    name: str
    scopes: list[str]
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None


class CredentialCreated(CredentialOut):
    token: str
    warning: str = "Store this token now; it is not retrievable later."
