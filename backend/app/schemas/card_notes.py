"""A person's notes on a Ticket at the REST boundary."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from .common import OutModel, StrictModel

NOTE_TEXT_MAX = 4000
"""A note holds 1 to this many characters, as ``ck_card_notes_text_length`` stores them."""

CardNoteText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_TEXT_MAX)
]


class CardNoteCreate(StrictModel):
    text: CardNoteText


class CardNoteUpdate(StrictModel):
    text: CardNoteText
    version: int = Field(ge=1, description="Expected current version for optimistic concurrency")


class CardNoteOut(OutModel):
    id: str
    card_id: str
    # The name at the time of writing; the id says whether the person reading it wrote it.
    author: str
    author_actor_id: str
    written_at: str
    updated_at: str
    text: str
    version: int


__all__ = ["NOTE_TEXT_MAX", "CardNoteCreate", "CardNoteOut", "CardNoteText", "CardNoteUpdate"]
