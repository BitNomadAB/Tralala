from __future__ import annotations

from pydantic import Field

from .common import CommentText, Id, Name, OutModel, StrictModel


class LabelOut(OutModel):
    id: str
    name: str
    color: str


class LabelCreate(StrictModel):
    name: Name
    color: str = "#64748b"


class LabelUpdate(StrictModel):
    name: Name | None = None
    color: str | None = None


class ChecklistItemCreate(StrictModel):
    text: Name
    position: int | None = Field(default=None, ge=0)


class ChecklistItemUpdate(StrictModel):
    text: Name | None = None
    completed: bool | None = None
    position: int | None = Field(default=None, ge=0)


class ChecklistItemOut(OutModel):
    id: str
    checklist_id: str
    text: str
    completed: bool
    position: int


class ChecklistCreate(StrictModel):
    title: Name


class ChecklistUpdate(StrictModel):
    title: Name | None = None


class ChecklistOut(OutModel):
    id: str
    card_id: str
    title: str
    position: int
    items: list[ChecklistItemOut] = Field(default_factory=list[ChecklistItemOut])


class CommentCreate(StrictModel):
    content: CommentText


class CommentOut(OutModel):
    id: str
    card_id: str
    actor_id: str
    actor_name: str | None = None
    actor_type: str | None = None
    content: str
    created_at: str
    updated_at: str


class CommentMentionOut(OutModel):
    id: str
    card_id: str
    comment_id: str
    agent_id: str
    agent_name: str
    status: str
    attempts: int = 0
    error: str | None = None
    response_comment_id: str | None = None
    tokens_used: int = 0
    role_template_id: str | None = None
    role_template_name: str | None = None
    role_source: str | None = None
    system_prompt_sha256: str | None = None
    requested_by_actor_id: str
    requested_by_type: str
    requested_by_name: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    can_retry: bool = False


class CardEventOut(OutModel):
    seq: int
    id: str
    card_id: str
    type: str
    payload: dict[str, object] = Field(default_factory=dict)
    actor_id: str | None = None
    actor_type: str | None = None
    actor_name: str | None = None
    created_at: str


class CardEventListOut(OutModel):
    items: list[CardEventOut]
    total: int


class ActivityOut(OutModel):
    id: str
    actor_id: str
    actor_type: str
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None = None
    timestamp: str
    changes: dict[str, object] | None = None


class IdRef(StrictModel):
    id: Id
