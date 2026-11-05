from __future__ import annotations

from pydantic import Field, field_validator

from ..core.dates import normalize_timestamp
from .common import Id, LongText, Name, OutModel, Priority, StrictModel, Summary
from .subresources import LabelOut


class CardCreate(StrictModel):
    list_id: Id
    title: Name
    description: LongText = ""
    summary: Summary = Field(
        default="", description="What the Ticket is about in a sentence or two (plain text)"
    )
    priority: Priority = "none"
    due_at: str | None = None
    labels: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("due_at", mode="after")
    @classmethod
    def _normalize_due_at(cls, value: str | None) -> str | None:
        return normalize_timestamp(value)


class CardUpdate(StrictModel):
    version: int = Field(ge=1, description="Expected current version for optimistic concurrency")
    title: Name | None = None
    description: LongText | None = None
    summary: Summary | None = Field(
        default=None, description="Replace the summary; an empty string removes it"
    )
    priority: Priority | None = None
    due_at: str | None = None
    clear_due_at: bool = False
    completed: bool | None = None
    labels: list[str] | None = Field(default=None, max_length=20)
    assignee_actor_id: Id | None = Field(
        default=None, description="Human actor id or enabled agent id"
    )
    clear_assignee: bool = False

    @field_validator("due_at", mode="after")
    @classmethod
    def _normalize_due_at(cls, value: str | None) -> str | None:
        return normalize_timestamp(value)


class CardMove(StrictModel):
    version: int = Field(ge=1)
    list_id: Id
    position: int = Field(ge=0, description="Target index within the destination list")


class CardTransfer(StrictModel):
    version: int = Field(ge=1)
    target_board_id: Id
    target_list_id: Id

    @field_validator("target_list_id")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target_list_id must not be empty")
        return value


class BulkCardCreate(StrictModel):
    cards: list[CardCreate] = Field(min_length=1, max_length=100)


class CardOut(OutModel):
    id: str
    board_id: str
    loop_id: str
    list_id: str
    title: str
    description: str
    summary: str = ""
    summary_source: str = Field(default="", description="plan, person, agent; empty without one")
    summary_stale: bool = Field(
        default=False, description="The title or description changed after the summary was written"
    )
    position: int
    priority: Priority
    due_at: str | None = None
    completed_at: str | None = None
    assignee_actor_id: str | None = None
    assignee_type: str | None = None
    assignee_name: str | None = None
    assigned_at: str | None = None
    assigned_by_actor_id: str | None = None
    created_at: str
    updated_at: str
    archived_at: str | None = None
    version: int
    labels: list[LabelOut] = Field(default_factory=list[LabelOut])
    checklist_total: int = 0
    checklist_completed: int = 0
    comment_count: int = 0
    ticket_key: str | None = None
    kind: str = "manual"
    phase_id: str | None = None
    phase_number: int | None = None
    required_actor: str = "any"
    execution_mode: str = "normal"
    human_action_required: bool = False
    human_action_reason: str = ""
    human_instructions: str = ""
    human_confirmed_at: str | None = None
    human_confirmed_by_actor_id: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_evidence: list[str] = Field(default_factory=list)
    ready: bool = True
    blockers: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    downstream_phase_numbers: list[int] = Field(default_factory=list[int])
    plan_item_id: str | None = None


class BoardTicketOut(CardOut):
    """Aggregate Board read; each item names the Loop that owns the Ticket."""

    loop_key: str | None = None
    loop_name: str | None = None


class CardListOut(OutModel):
    items: list[CardOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class BulkCreateResult(OutModel):
    created: list[CardOut]
    failed: list[dict[str, object]]
