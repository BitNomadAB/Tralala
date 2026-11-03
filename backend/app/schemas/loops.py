"""Schemas for Loop planning, delivery, QA and history.

Machine-oriented payloads are strict: unknown fields are rejected and the structured plan is the
authoritative representation. Human-facing Markdown is rendered by the server from validated
structures, so a model cannot invent, omit or reorder work only in the summary view.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field, field_validator

from .common import Id, LongText, Name, OutModel, Priority, StrictModel

DocumentKind = Literal["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"]
DOCUMENT_KINDS: tuple[str, ...] = get_args(DocumentKind)
LoopStage = Literal[
    "draft",
    "analysis_review",
    "planning",
    "roadmap_review",
    "ready",
    "in_progress",
    "replanning",
    "awaiting_qa",
    "completed",
    "cancelled",
]
# One authority per enumeration: the literals above feed both the validators and the services.
LOOP_STAGES: tuple[str, ...] = get_args(LoopStage)
ApprovalScope = Literal["analysis", "roadmap", "implementation", "qa"]
APPROVAL_SCOPES: tuple[str, ...] = get_args(ApprovalScope)
RequiredActor = Literal["any", "human"]
ExecutionMode = Literal["normal", "pre_phase_gate"]

ShortText = Annotated[str, Field(max_length=500)]
BodyText = Annotated[str, Field(max_length=40_000)]

# --- Loop ownership ---------------------------------------------------------------


class LoopCreate(StrictModel):
    name: Name
    goal: LongText = ""
    column_names: list[Name] | None = Field(
        default=None,
        max_length=30,
        description="Optional column names; defaults to the board's Loop defaults",
    )


class LoopUpdate(StrictModel):
    version: int = Field(ge=1)
    name: Name | None = None
    goal: LongText | None = None


class LoopCancel(StrictModel):
    version: int = Field(ge=1)
    reason: LongText = ""


class LoopOut(OutModel):
    id: str
    board_id: str
    name: str
    goal: str
    key: str
    key_prefix: str
    sequence: int
    stage: LoopStage
    version: int
    created_at: str
    updated_at: str
    archived_at: str | None = None
    cancelled_at: str | None = None
    completed_at: str | None = None
    history_id: str | None = None
    documents: dict[str, object] = Field(default_factory=dict)
    plan: dict[str, object] | None = None
    qa: dict[str, object] | None = None
    progress: dict[str, object] = Field(default_factory=dict)
    warnings: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])


# --- Documents --------------------------------------------------------------------


class InfoRevisionWrite(StrictModel):
    content: BodyText
    note: ShortText = ""
    expected_revision_id: Id | None = Field(
        default=None, description="Current Info revision the author edited from"
    )


class AnalysisFinding(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=40)]
    title: ShortText
    category: Literal[
        "reuse", "change", "risk", "blocker", "decision", "legal", "security", "question"
    ]
    technical_detail: BodyText
    plain_language: ShortText
    evidence: BodyText = ""
    sources: list[ShortText] = Field(default_factory=list, max_length=30)


class AnalysisPayload(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    outcome: ShortText
    scope: list[ShortText] = Field(default_factory=list, max_length=30)
    non_goals: list[ShortText] = Field(default_factory=list, max_length=30)
    findings: list[AnalysisFinding] = Field(default_factory=list[AnalysisFinding], max_length=100)
    assumptions: list[ShortText] = Field(default_factory=list, max_length=50)
    open_questions: list[ShortText] = Field(default_factory=list, max_length=50)
    options: list[ShortText] = Field(default_factory=list, max_length=20)
    recommendation: BodyText = ""
    verification: list[ShortText] = Field(default_factory=list, max_length=30)
    sources: list[ShortText] = Field(default_factory=list, max_length=50)
    repository_revision: Annotated[str, Field(max_length=120)] = ""

    @field_validator("findings")
    @classmethod
    def _unique_finding_ids(cls, value: list[AnalysisFinding]) -> list[AnalysisFinding]:
        seen: set[str] = set()
        for finding in value:
            if finding.id in seen:
                raise ValueError(f"duplicate finding id: {finding.id}")
            seen.add(finding.id)
        return value


class PlanTicket(StrictModel):
    id: Id
    title: Name
    objective: LongText = ""
    instructions: LongText = ""
    required_actor: RequiredActor = "any"
    execution_mode: ExecutionMode = "normal"
    prerequisite_phase_ids: list[Id] = Field(default_factory=list, max_length=50)
    prerequisite_ticket_ids: list[Id] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[ShortText] = Field(default_factory=list, max_length=30)
    expected_evidence: list[ShortText] = Field(default_factory=list, max_length=30)
    human_action_reason: LongText = ""
    human_instructions: LongText = ""
    note: LongText = ""
    priority: Priority = "none"

    @field_validator("human_action_reason", "human_instructions")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PlanPhase(StrictModel):
    id: Id
    number: int = Field(ge=1, le=99)
    name: Name
    objective: LongText = ""
    entry_conditions: list[ShortText] = Field(default_factory=list, max_length=30)
    exit_conditions: list[ShortText] = Field(default_factory=list, max_length=30)
    prerequisite_phase_ids: list[Id] = Field(default_factory=list, max_length=50)
    prerequisite_ticket_ids: list[Id] = Field(default_factory=list, max_length=50)
    narrative: LongText = ""
    tickets: list[PlanTicket] = Field(default_factory=list[PlanTicket], max_length=100)


class PlanPayload(StrictModel):
    """A structured RoadMapAI payload. Ticket keys and Loop references are added by the server."""

    schema_version: int = Field(default=1, ge=1, le=1)
    summary: LongText = ""
    phases: list[PlanPhase] = Field(min_length=1, max_length=30)


class CandidateSubmission(StrictModel):
    kind: Literal["analysis", "roadmap"]
    analysis: AnalysisPayload | None = None
    plan: PlanPayload | None = None
    source_info_revision_id: Id | None = None
    source_analysis_ai_revision_id: Id | None = None
    source_analysis_revision_id: Id | None = None
    expected_info_revision_id: Id | None = Field(
        default=None, description="Current Info revision the candidate was written from"
    )
    expected_analysis_revision_id: Id | None = Field(
        default=None,
        description="Current technical analysis (analysis_ai) revision a RoadMap was written from",
    )
    provenance: dict[str, object] = Field(default_factory=dict)

    @field_validator("provenance")
    @classmethod
    def _bounded_provenance(cls, value: dict[str, object]) -> dict[str, object]:
        if len(value) > 20:
            raise ValueError("provenance accepts at most 20 entries")
        return value


class DocumentOut(OutModel):
    loop_id: str
    kind: str
    state: str
    current_revision_id: str | None = None
    current_revision_number: int | None = None
    current_content: str | None = None
    current_payload: dict[str, object] | None = None
    current_created_at: str | None = None
    approved_revision_id: str | None = None
    approved_revision_number: int | None = None
    approved_content: str | None = None
    source_revisions: dict[str, object] = Field(default_factory=dict)
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
    revisions: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    generation_available: bool = True
    render: list[str] = Field(default_factory=list)


class DocumentListOut(OutModel):
    loop_id: str
    loop_version: int
    documents: dict[str, DocumentOut]
    approvals: dict[str, dict[str, object] | None] = Field(default_factory=dict)


class ApprovalRequest(StrictModel):
    decision: Literal["approved", "changes_requested"]
    version: int = Field(ge=1)
    revisions: dict[str, Id] = Field(
        default_factory=dict,
        description="Exact revisions the reviewer saw, keyed by document kind",
    )
    feedback: LongText = ""


class ApprovalOut(OutModel):
    id: str
    loop_id: str
    scope: str
    decision: str
    reviewer_actor_id: str
    reviewer_name: str
    feedback: str = ""
    revisions: dict[str, object] = Field(default_factory=dict)
    created_at: str
    superseded_at: str | None = None


class ScopeResetRequest(StrictModel):
    version: int = Field(ge=1)


class ScopeResetOut(OutModel):
    scope: str
    approval_id: str | None = None
    cleared: list[str] = Field(default_factory=list)
    version: int


# --- Publication ------------------------------------------------------------------

class PlanItemOut(OutModel):
    id: str
    key: str
    title: str
    phase_id: str
    phase_number: int
    objective: str = ""
    instructions: str = ""
    required_actor: str
    execution_mode: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_evidence: list[str] = Field(default_factory=list)
    human_action_reason: str = ""
    human_instructions: str = ""
    prerequisite_ticket_ids: list[str] = Field(default_factory=list)
    prerequisite_phase_ids: list[str] = Field(default_factory=list)
    card_id: str | None = None
    completed_at: str | None = None
    ready: bool = True
    blockers: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    human_action_required: bool = False


class PhaseOut(OutModel):
    id: str
    number: int
    name: str
    objective: str = ""
    entry_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    prerequisite_phase_ids: list[str] = Field(default_factory=list)
    prerequisite_ticket_ids: list[str] = Field(default_factory=list)
    seat: str = "pending"
    blocked_by: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    tickets: list[PlanItemOut] = Field(default_factory=list[PlanItemOut])


class PlanOut(OutModel):
    loop_id: str
    plan_id: str | None = None
    revision_number: int | None = None
    status: str = "none"
    activated_at: str | None = None
    approved_at: str | None = None
    phases: list[PhaseOut] = Field(default_factory=list[PhaseOut])
    warnings: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])


class ReadinessOut(OutModel):
    loop_id: str
    stage: LoopStage
    execution_allowed: bool
    blocked_reason: dict[str, object] | None = None
    items: list[PlanItemOut] = Field(default_factory=list[PlanItemOut])
    phases: list[PhaseOut] = Field(default_factory=list[PhaseOut])


class ChangePreviewOut(OutModel):
    added: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    changed: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    retained: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    superseded: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    revalidation_required: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])


class HumanConfirmation(StrictModel):
    version: int = Field(ge=1)
    note: ShortText = ""
    evidence: BodyText = ""


# --- Generation -------------------------------------------------------------------

class GenerationRequest(StrictModel):
    purpose: Literal["analysis", "roadmap", "qa"]
    agent_id: Id | None = None
    instructions: LongText = ""


class LoopAgentPreferencesUpdate(StrictModel):
    """Agent per generation purpose for one Loop.

    Omitted fields keep their stored value; an explicit ``null`` clears that purpose.
    """

    analysis_agent_id: Id | None = None
    roadmap_agent_id: Id | None = None
    qa_agent_id: Id | None = None


class LoopAgentPreferencesOut(OutModel):
    loop_id: str
    analysis_agent_id: str | None = None
    roadmap_agent_id: str | None = None
    qa_agent_id: str | None = None


class GenerationRunOut(OutModel):
    id: str
    loop_id: str
    purpose: str
    status: str
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 0
    output: dict[str, object] = Field(default_factory=dict)
    source_revisions: dict[str, object] = Field(default_factory=dict)
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    model: str | None = None
    agent_name: str | None = None
    usage: dict[str, object] = Field(default_factory=dict)


class LoopContextOut(OutModel):
    loop_id: str
    loop_key: str
    loop_name: str
    stage: str
    documents: dict[str, object]
    plan: dict[str, object] | None = None
    tickets: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    schemas: dict[str, object] = Field(default_factory=dict)


# --- QA ---------------------------------------------------------------------------

class ImplementationAcceptance(StrictModel):
    version: int = Field(ge=1)
    accepted: bool = True
    qa_status: Literal["not_tested", "tested_with_issues", "passed"] = "not_tested"
    attestation: dict[str, object] = Field(default_factory=dict)
    note: LongText = ""


QaResultStatus = Literal["passed", "failed", "blocked", "not_run", "not_applicable"]

QA_SCENARIO_KINDS = ("happy_path", "failure_path", "regression")


class QaScenario(StrictModel):
    """One scenario shared by the AI-oriented and human-oriented instruction views."""

    id: Annotated[str, Field(min_length=1, max_length=40)]
    title: ShortText
    kind: Literal["happy_path", "failure_path", "regression"]
    prerequisites: list[ShortText] = Field(default_factory=list, max_length=20)
    steps_ai: list[ShortText] = Field(default_factory=list, max_length=30)
    steps_human: list[ShortText] = Field(default_factory=list, max_length=30)
    expected_result: BodyText
    evidence: list[ShortText] = Field(default_factory=list, max_length=20)

    @field_validator("steps_human")
    @classmethod
    def _human_steps_present(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("a human-oriented view needs numbered steps")
        return value


class QaInstructions(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    summary: ShortText = ""
    known_risks: list[ShortText] = Field(default_factory=list, max_length=30)
    scenarios: list[QaScenario] = Field(min_length=1, max_length=100)

    @field_validator("scenarios")
    @classmethod
    def _unique_ids(cls, value: list[QaScenario]) -> list[QaScenario]:
        seen: set[str] = set()
        for scenario in value:
            if scenario.id in seen:
                raise ValueError(f"duplicate scenario id: {scenario.id}")
            seen.add(scenario.id)
        return value


class QaResultInput(StrictModel):
    scenario_id: Annotated[str, Field(min_length=1, max_length=60)]
    status: QaResultStatus
    reason: ShortText = ""
    evidence: BodyText = ""
    tested_baseline: Annotated[str, Field(max_length=200)] = ""


class QaResultSubmission(StrictModel):
    cycle_id: Id | None = None
    results: list[QaResultInput] = Field(min_length=1, max_length=200)


class QaDecision(StrictModel):
    version: int = Field(ge=1)
    cycle_id: Id
    decision: Literal["accepted", "rejected"]
    not_applicable_approvals: list[str] = Field(default_factory=list, max_length=50)
    note: LongText = ""
    idempotency_key: Annotated[str, Field(max_length=200)] | None = None


class QaCycleOut(OutModel):
    id: str
    loop_id: str
    cycle_number: int
    status: str
    card_id: str | None = None
    instruction_revision: int = 0
    delivery_baseline: str = ""
    ai_instructions: dict[str, object] = Field(default_factory=dict)
    human_instructions: dict[str, object] = Field(default_factory=dict)
    results: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])
    attestation: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    decided_at: str | None = None
    decision_note: str = ""


# --- History ----------------------------------------------------------------------

HistorySourceKind = Literal["native", "imported_legacy"]


class HistorySummary(OutModel):
    id: str
    source_kind: str
    conformance: str
    board_id: str
    loop_id: str | None = None
    loop_key: str | None = None
    loop_name: str
    qa_status: str
    completed_at: str | None = None
    imported_at: str | None = None
    created_at: str
    content_hash: str
    warnings: list[str] = Field(default_factory=list)
    label: str = ""


class HistoryDetail(HistorySummary):
    envelope: dict[str, object] = Field(default_factory=dict)
    artifacts: list[dict[str, object]] = Field(default_factory=list[dict[str, object]])


class LegacyImportRequest(StrictModel):
    loop_name: Name
    source_project: Annotated[str, Field(max_length=200)] | None = None
    source_reference: Annotated[str, Field(max_length=200)] | None = None
    source_format: Annotated[str, Field(max_length=60)] | None = None
    source_version: Annotated[str, Field(max_length=60)] | None = None
    reported_metadata: dict[str, object] = Field(default_factory=dict)
    documents: dict[str, BodyText] = Field(default_factory=dict)
    reported_qa_status: Annotated[str, Field(max_length=60)] | None = None
    raw_text: BodyText = ""
    idempotency_key: Annotated[str, Field(max_length=200)] | None = None
