from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

SUMMARY_MAX_CHARS = 400


def _one_paragraph(value: object) -> object:
    """A summary is one paragraph: every run of whitespace, line breaks included, is one space."""
    return " ".join(value.split()) if isinstance(value, str) else value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=20_000)]
# What a Ticket is about, in a sentence or two: what a list of Tickets shows instead of everything.
Summary = Annotated[
    str, StringConstraints(max_length=SUMMARY_MAX_CHARS), BeforeValidator(_one_paragraph)
]
# The face for people of a Ticket (``services/ticket_face.py`` holds its counts and rules): a text
# of a few sentences and a short list item, bounded here so a payload stays small; the list bound is
# far above the face's own limits so a long list reaches the check that says how to split it.
FACE_TEXT_MAX_CHARS = 400
FACE_ITEM_MAX_CHARS = 140
FACE_LIST_MAX_ITEMS = 20
FaceText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=FACE_TEXT_MAX_CHARS)]
FaceItem = Annotated[str, StringConstraints(strip_whitespace=True, max_length=FACE_ITEM_MAX_CHARS)]
FaceList = Annotated[list[FaceItem], Field(max_length=FACE_LIST_MAX_ITEMS)]
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
