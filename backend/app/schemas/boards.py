from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import LongText, Name, OutModel, StrictModel

BoardStatus = Literal["active", "archived", "maintenance", "error", "migration_failed"]


class BoardCreate(StrictModel):
    name: Name
    description: LongText = ""
    lists: list[Name] | None = Field(
        default=None, description="Optional initial list names; defaults to Backlog..Done"
    )
    template_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional saved template whose description, lists and labels are applied",
    )
    repository_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Repositories this board is about; chosen from the repository list",
    )


class BoardUpdate(StrictModel):
    name: Name | None = None
    description: LongText | None = None
    repository_ids: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Replace the board's repository selection; omit to keep it",
    )


class BoardOut(OutModel):
    id: str
    name: str
    description: str
    status: BoardStatus
    created_at: str
    updated_at: str
    archived_at: str | None = None
    schema_version: int
    schema_revision: str | None = None
    loop_count: int = 0
    list_count: int = 0
    card_count: int = 0
    repository_ids: list[str] = Field(default_factory=list)


class BoardListOut(OutModel):
    items: list[BoardOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class BoardDelete(StrictModel):
    confirm_name: Name
