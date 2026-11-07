from __future__ import annotations

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


class DiscussionAnswerOut(OutModel):
    """A participant's answer in the standard (version 1), stored beside its prose.

    ``format``: ``structured`` (valid at once), ``repaired`` (valid after one repair) or ``prose``
    (never valid: ``position`` is ``unclear`` and ``problem`` says what was wrong).
    """

    version: int = 1
    format: str
    position: str
    recommendation: str = ""
    pros: list[str] = Field(default_factory=list[str])
    cons: list[str] = Field(default_factory=list[str])
    conditions: list[str] = Field(default_factory=list[str])
    open_questions: list[str] = Field(default_factory=list[str])
    confidence: str | None = None
    problem: str | None = None


class DiscussionStanceOut(OutModel):
    """One participant's latest answer: where it stands and what it recommends."""

    participant_id: str
    participant: str
    position: str
    recommendation: str = ""
    confidence: str | None = None
    format: str
    message_id: str
    round_number: int = 0


class DiscussionPointOut(OutModel):
    text: str
    participants: list[str] = Field(default_factory=list[str])


class DiscussionSuggestionOut(OutModel):
    verdict: str
    reason: str


class DiscussionSynthesisOut(OutModel):
    """Decision support Tralala computes after a round from the latest answers; a suggestion,
    never a decision."""

    version: int = 1
    kind: str = "decision_support"
    written_by: str = "tralala"
    round_id: str | None = None
    round_number: int
    thread_round: int
    suggestion: DiscussionSuggestionOut
    counts: dict[str, int] = Field(default_factory=dict[str, int])
    go: list[DiscussionStanceOut] = Field(default_factory=list[DiscussionStanceOut])
    stop: list[DiscussionStanceOut] = Field(default_factory=list[DiscussionStanceOut])
    unclear: list[DiscussionStanceOut] = Field(default_factory=list[DiscussionStanceOut])
    conditions: list[DiscussionPointOut] = Field(default_factory=list[DiscussionPointOut])
    open_questions: list[DiscussionPointOut] = Field(default_factory=list[DiscussionPointOut])
    missing: list[str] = Field(default_factory=list[str])


class DiscussionVoteOut(OutModel):
    participant_id: str
    display_name: str | None = None
    position: str
    justification: str = ""
    round_number: int = 0
    created_at: str


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
    # A participant's structured answer; null for a person's message and an answer before it.
    answer: DiscussionAnswerOut | None = None


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
    synthesis: DiscussionSynthesisOut | None = None


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
    rounds: list[DiscussionRoundOut] = Field(default_factory=list[DiscussionRoundOut])


class DiscussionRunListOut(OutModel):
    items: list[DiscussionRunOut]
    total: int


class DiscussionEventOut(OutModel):
    seq: int
    id: str
    discussion_id: str
    type: str
    payload: dict[str, object] = Field(default_factory=dict)
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
    participants: list[DiscussionParticipantOut] = Field(
        default_factory=list[DiscussionParticipantOut]
    )
    messages: list[DiscussionMessageOut] = Field(default_factory=list[DiscussionMessageOut])
    # The newest round's decision support, each participant's current position, and the history
    # of position changes.
    synthesis: DiscussionSynthesisOut | None = None
    positions: list[DiscussionStanceOut] = Field(default_factory=list[DiscussionStanceOut])
    votes: list[DiscussionVoteOut] = Field(default_factory=list[DiscussionVoteOut])
    active_run: DiscussionRunOut | None = None
    runs: list[DiscussionRunOut] = Field(default_factory=list[DiscussionRunOut])


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
