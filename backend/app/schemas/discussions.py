from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import Id, LongText, Name, OutModel, StrictModel

DiscussionStatus = str


class DiscussionCreate(StrictModel):
    card_id: Id
    title: Name | None = None
    goal: LongText = Field(min_length=1)
    mode: str = Field(default="manual", pattern="^(manual|roundtable|autonomous)$")
    participant_ids: list[Id] = Field(default_factory=list, max_length=12)
    # Four rounds is where a discussion still adds something: with sequential answers and a review
    # round before consensus, a thread either converges by two or repeats itself.
    max_rounds: int = Field(default=3, ge=1, le=4)


class DiscussionRunStart(StrictModel):
    """Run one round by default; ``autonomous`` keeps the loop going until the thread decides."""

    rounds: int | None = Field(default=None, ge=1, le=4)
    autonomous: bool = False
    token_budget: int | None = Field(default=None, ge=0, le=5_000_000)
    time_budget_seconds: int | None = Field(default=None, ge=0, le=3600)


class DiscussionMessageCreate(StrictModel):
    content: LongText = Field(min_length=1)
    parent_message_id: Id | None = None


class DiscussionReview(StrictModel):
    decision: str = Field(pattern="^(approve|veto|rework)$")
    reason: LongText = ""


class DiscussionParticipantOut(OutModel):
    id: str
    participant_id: str
    participant_type: str
    display_name: str
    role_template_id: str | None = None
    role_template_name: str | None = None
    role_source: str = "template"
    system_prompt_sha256: str
    snapshot_at: str


class DiscussionMessageOut(OutModel):
    id: str
    parent_message_id: str | None = None
    author_actor_id: str
    author_type: str
    author_name: str
    author_role: str | None = None
    content: str
    status: str
    model: str | None = None
    round_number: int = 0
    created_at: str


class DiscussionRoundOut(OutModel):
    id: str
    run_id: str
    round_number: int
    status: str
    answers: int = 0
    failures: int = 0
    repeats: int = 0
    tokens_used: int = 0
    elapsed_ms: int = 0
    created_at: str
    finished_at: str


class DiscussionRunOut(OutModel):
    id: str
    discussion_id: str
    status: str
    autonomy: bool = False
    rounds_requested: int = 1
    rounds_completed: int = 0
    token_budget: int | None = None
    tokens_used: int = 0
    time_budget_seconds: int | None = None
    elapsed_ms: int = 0
    stop_reason: str | None = None
    error: str | None = None
    started_by_name: str
    created_at: str
    started_at: str
    finished_at: str | None = None
    rounds: list[DiscussionRoundOut] = Field(default_factory=list)


class DiscussionRunListOut(OutModel):
    items: list[DiscussionRunOut]
    total: int


class DiscussionEventOut(OutModel):
    seq: int
    id: str
    discussion_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: str | None = None
    actor_type: str | None = None
    actor_name: str | None = None
    created_at: str


class DiscussionEventListOut(OutModel):
    items: list[DiscussionEventOut]
    total: int


class DiscussionOut(OutModel):
    id: str
    card_id: str
    card_title: str | None = None
    ticket_key: str | None = None
    loop_id: str | None = None
    loop_key: str | None = None
    loop_name: str | None = None
    title: str
    goal: str
    mode: str
    status: str
    run_state: str = "idle"
    created_by_actor_id: str
    created_by_name: str
    max_rounds: int
    round_count: int = 0
    tokens_used: int = 0
    elapsed_ms: int = 0
    created_at: str
    updated_at: str
    last_activity_at: str
    participant_count: int = 0
    message_count: int = 0
    # Set on a message response: started, already_running, thread_closed or no_participants.
    auto_run: str | None = None
    participants: list[DiscussionParticipantOut] = Field(default_factory=list)
    messages: list[DiscussionMessageOut] = Field(default_factory=list)
    active_run: DiscussionRunOut | None = None
    runs: list[DiscussionRunOut] = Field(default_factory=list)


class DiscussionListOut(OutModel):
    items: list[DiscussionOut]
    total: int


class DiscussionBoardOut(OutModel):
    """One entrance in the Discussions board list, ordered by the newest thread activity."""

    board_id: str
    board_name: str
    status: str
    discussion_count: int = 0
    open_count: int = 0
    last_activity_at: str | None = None


class DiscussionBoardListOut(OutModel):
    items: list[DiscussionBoardOut]
    total: int
