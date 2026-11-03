from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=20_000)]
# A comment carries a progress note or a completion summary with its evidence, not a title.
CommentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]
Id = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Priority = Literal["none", "low", "medium", "high", "urgent"]


class StrictModel(BaseModel):
    """Rejects unknown fields instead of silently accepting them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OutModel(BaseModel):
    """Response model: documented in OpenAPI while tolerating additive fields."""

    model_config = ConfigDict(extra="allow")


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool
