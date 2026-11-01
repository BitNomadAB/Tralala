from __future__ import annotations

from pydantic import Field

from .common import Name, OutModel, StrictModel


class ListCreate(StrictModel):
    name: Name
    position: int | None = Field(
        default=None, ge=0, description="Target index; appends when omitted"
    )


class ListUpdate(StrictModel):
    name: Name | None = None


class ListMove(StrictModel):
    position: int = Field(ge=0, description="Target index among non-archived lists")


class ListOut(OutModel):
    id: str
    board_id: str
    name: str
    position: int
    created_at: str
    updated_at: str
    archived_at: str | None = None
    card_count: int = 0
