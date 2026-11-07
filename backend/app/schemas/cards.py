from __future__ import annotations

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..core.dates import normalize_timestamp
from .common import Id, LongText, Name, OutModel, Priority, StrictModel, Summary
from .subresources import LabelOut

# Where a Ticket's work is done: it describes the work and assigns nothing. ``unknown`` is what
# every Ticket created before the field existed reads, so nothing old claims what nobody said.
Workplace = Literal["codebase", "outside", "unknown"]
WORKPLACES: tuple[str, ...] = get_args(Workplace)
# What a Ticket waits for; ``access`` is a system, key, account, setting or machine, ``third_party``
# a supplier, a customer, a lawyer and the like.
WaitingFor = Literal["nothing", "decision", "information", "access", "third_party"]
WAITING_FOR: tuple[str, ...] = get_args(WaitingFor)
# A wait someone sets: every value but ``nothing``.
Wait = Literal["decision", "information", "access", "third_party"]
WAITS: tuple[str, ...] = get_args(Wait)
WAITING_REASON_CHARS = 500
WaitingReason = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=WAITING_REASON_CHARS)
]


def wait_needs_reason(waiting_for: str, reason: str) -> None:
    """A wait says why; waiting for nothing has no reason."""
    if waiting_for != "nothing" and not reason:
        raise ValueError("waiting_reason is required when waiting_for is not nothing")
    if waiting_for == "nothing" and reason:
        raise ValueError("waiting_reason is only given with a wait")


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
    workplace: Workplace = Field(
        default="unknown",
        description="Where the work is done: codebase, outside or unknown; it assigns nothing",
    )
    waiting_for: WaitingFor = Field(
        default="nothing", description="nothing, decision, information, access or third_party"
    )
    waiting_reason: WaitingReason = Field(
        default="", description="Why it waits; required with a wait"
    )

    @field_validator("due_at", mode="after")
    @classmethod
    def _normalize_due_at(cls, value: str | None) -> str | None:
        return normalize_timestamp(value)

    @model_validator(mode="after")
    def _reason(self) -> Self:
        wait_needs_reason(self.waiting_for, self.waiting_reason)
        return self


class TicketWorkplaceUpdate(StrictModel):
    """Where a Ticket's work is done; it describes the work, so ``cards:write`` may change it."""

    version: int = Field(ge=1, description="Expected current version for optimistic concurrency")
    workplace: Workplace


class TicketWaitSet(StrictModel):
    """A wait on a Ticket with its reason: what has to be answered before the work goes on."""

    version: int = Field(ge=1, description="Expected current version for optimistic concurrency")
    waiting_for: Wait
    reason: WaitingReason = Field(min_length=1, description="What is needed, at most 500 chars")


class TicketWaitClear(StrictModel):
    """Clearing a wait is a person's act."""

    version: int = Field(ge=1, description="Expected current version for optimistic concurrency")


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
    workplace: Workplace = "unknown"
    waiting_for: WaitingFor = "nothing"
    waiting_reason: str = ""
    waiting_set_at: str | None = None
    waiting_set_by: str | None = None
    state: str | None = Field(
        default=None,
        description="ready, needs_input or blocked, computed on every read; null once completed",
    )
    needs_person: bool = Field(
        default=False, description="needs_input, or ready with human_action_required"
    )


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
