from __future__ import annotations

from pydantic import Field

from .common import Color, LongText, Name, OutModel, StrictModel


class TemplateLabel(StrictModel):
    name: Name
    color: Color


class TemplateCreate(StrictModel):
    name: Name
    description: LongText = ""
    lists: list[Name] = Field(
        default_factory=list,
        max_length=50,
        description="Initial list names, in board order; empty means the default Backlog..Done",
    )
    labels: list[TemplateLabel] = Field(default_factory=list, max_length=50)


class TemplateUpdate(StrictModel):
    name: Name | None = None
    description: LongText | None = None
    lists: list[Name] | None = Field(default=None, max_length=50)
    labels: list[TemplateLabel] | None = Field(default=None, max_length=50)


class TemplateFromBoard(StrictModel):
    name: Name
    description: LongText = ""


class TemplateOut(OutModel):
    id: str
    name: str
    description: str
    lists: list[str] = Field(default_factory=list)
    labels: list[TemplateLabel] = Field(default_factory=list)
    created_at: str
    updated_at: str
    list_count: int = 0


class TemplateListOut(OutModel):
    items: list[TemplateOut]
    total: int
