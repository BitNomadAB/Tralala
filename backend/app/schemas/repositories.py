"""Repository schemas: a registry-level list, linked to boards from the board dialog.

A response exposes whether a token exists and a short hint, never the token itself.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import OutModel, StrictModel

Provider = Literal["github"]

RepositoryName = Annotated[str, Field(min_length=1, max_length=120)]
RepositoryUrl = Annotated[str, Field(min_length=1, max_length=500)]
Branch = Annotated[str, Field(min_length=1, max_length=200)]
Token = Annotated[str, Field(min_length=1, max_length=500)]


class RepositoryCreate(StrictModel):
    name: RepositoryName | None = Field(
        default=None, description="Label for the list; defaults to the repository name"
    )
    url: RepositoryUrl
    branch: Branch | None = None
    enabled: bool = True
    token: Token | None = Field(
        default=None, description="Read-only access token; stored sealed and never returned"
    )


class RepositoryUpdate(StrictModel):
    name: RepositoryName | None = None
    url: RepositoryUrl | None = None
    branch: Branch | None = None
    enabled: bool | None = None
    token: Token | None = Field(default=None)
    clear_token: bool = False


class RepositoryBoardOut(OutModel):
    id: str
    name: str


class RepositoryOut(OutModel):
    id: str
    name: str
    provider: Provider
    url: str
    branch: str | None = None
    enabled: bool = True
    has_token: bool = False
    token_hint: str | None = None
    boards: list[RepositoryBoardOut] = Field(default_factory=list[RepositoryBoardOut])
    last_checked_at: str | None = None
    last_check_status: str | None = None
    last_check_detail: str | None = None
    created_at: str
    updated_at: str


class RepositoryCheckOut(OutModel):
    status: str
    detail: str | None = None
    default_branch: str | None = None
    private: bool | None = None
    size_kb: int | None = None
    checked_at: str
