"""LoopDocumentService on an in-memory board: the documents view and revision history, Info,
analysis and RoadMap candidates, reviews bound to exact revisions, scope resets, what a changed
input invalidates, and the results a generation run stores.

The service runs its real code, with the real plan service, against the typed fakes in
``tests/unit/fakes`` (repositories, unit of work, registry checks), with a fixed clock and id
source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure, VersionConflict
from app.db.generated.board import LoopGenerationRunsRow, LoopsRow
from app.schemas.briefs import BriefWrite, HumanBrief, RoadmapBrief
from app.schemas.loops import (
    AnalysisPayload,
    ApprovalRequest,
    CandidateSubmission,
    InfoRevisionWrite,
    PlanPayload,
    ScopeResetRequest,
)
from app.services.loop_documents import (
    MAX_DOCUMENT_PAYLOAD,
    LoopDocumentService,
    Review,
    content_hash,
    render_analysis,
    render_roadmap,
)
from app.services.loop_documents_views import HumanViewStart
from app.services.loop_plans import LoopPlanService
from tests.unit.faces import FACE
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    list_row,
    loop_row,
    qa_cycle_row,
)
from tests.unit.signs import SIGN

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
SCOPES = frozenset({"loops:read", "loops:write", "loops:generate", "loops:review"})
HUMAN = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES, request_id="req-1"
)
AGENT = ActorContext(actor_id="agent-1", actor_type="agent", actor_name="Bot", scopes=SCOPES)
P1, P2 = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
T1, T2 = "00000000-0000-4000-8000-000000000011", "00000000-0000-4000-8000-000000000012"


class Ids:
    """new-1, new-2, ... in call order, shared by the document and the plan service."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    service: LoopDocumentService

    @property
    def loop(self) -> LoopsRow:
        return self.state.loops[LOOP]

    @property
    def repos(self) -> FakeBoardRepositories:
        return FakeBoardRepositories(self.state)


def world(stage: str = "draft") -> World:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage=stage)}
    state.lists = {"todo": list_row("todo", LOOP, 1024)}
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    ids = Ids()
    plans = LoopPlanService(clock=lambda: NOW, new_id=ids)
    service = LoopDocumentService(checks, store, plans, clock=lambda: NOW, new_id=ids)
    return World(state, store, checks, service)


ANALYSIS = AnalysisPayload.model_validate(
    {
        "outcome": "Verify addresses",
        "findings": [
            {
                "id": "F-01",
                "title": "Reuse auth",
                "category": "reuse",
                "technical_detail": "auth.py",
                "plain_language": "Extend sign-in.",
            }
        ],
        "recommendation": "Pick a provider.",
    }
)
PLAN = PlanPayload.model_validate(
    {
        "summary": "Two phases",
        "phases": [
            {
                "id": P1,
                "number": 1,
                "name": "Database",
                "tickets": [
                    {**FACE, "id": T1, "title": "Add columns", "acceptance_criteria": ["ok"]}
                ],
            },
            {
                "id": P2,
                "number": 2,
                "name": "Sign-in",
                "prerequisite_phase_ids": [P1],
                "tickets": [
                    {
                        **FACE,
                        "id": T2,
                        "title": "Confirm",
                        "required_actor": "human",
                        "human_action_reason": "Legal",
                        "human_instructions": "Sign",
                        "prerequisite_ticket_ids": [T1],
                    }
                ],
            },
        ],
    }
)


def info(w: World, content: str = "Users must confirm.", actor: ActorContext = HUMAN) -> None:
    w.service.save_info(actor, BOARD_ID, LOOP, InfoRevisionWrite(content=content))


def analysis(w: World, payload: AnalysisPayload = ANALYSIS) -> None:
    w.service.submit_candidate(
        HUMAN, BOARD_ID, LOOP, CandidateSubmission(kind="analysis", analysis=payload)
    )


def roadmap(w: World, payload: PlanPayload = PLAN) -> None:
    w.service.submit_candidate(
        HUMAN, BOARD_ID, LOOP, CandidateSubmission(kind="roadmap", plan=payload)
    )


def review(w: World, scope: str, decision: str = "approved", **extra: object) -> Review:
    request = ApprovalRequest.model_validate(
        {"decision": decision, "version": w.loop.version, **extra}
    )
    return w.service.review(HUMAN, BOARD_ID, LOOP, scope, request)


def approved_analysis(w: World) -> None:
    info(w)
    analysis(w)
    review(w, "analysis")


def current(w: World, kind: str) -> str:
    row = w.repos.documents.current(LOOP, kind)
    assert row is not None
    return row.id


# --- the documents view and the revision history -------------------------------------------


def test_an_empty_loop_shows_five_empty_documents_and_no_approvals() -> None:
    w = world()
    view = w.service.documents(BOARD_ID, LOOP)
    assert (view["loop_id"], view["loop_version"], view["approvals"]) == (LOOP, 1, {})
    assert list(view["documents"]) == ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"]
    empty = view["documents"]["info"]
    assert empty["state"] == "empty"
    assert (empty["current_revision_id"], empty["current_payload"], empty["source_revisions"]) == (
        None,
        None,
        {},
    )
    assert (empty["stale"], empty["stale_reasons"], empty["revisions"]) == (False, [], [])
    assert w.checks.calls == [("require_row", BOARD_ID)]


def test_the_documents_view_shows_current_approved_sources_and_the_newest_revisions() -> None:
    w = world()
    approved_analysis(w)
    view = w.service.documents(BOARD_ID, LOOP)
    technical = view["documents"]["analysis_ai"]
    assert technical["state"] == "approved"
    assert technical["current_revision_id"] == technical["approved_revision_id"]
    assert technical["current_payload"] == ANALYSIS.model_dump()
    assert technical["source_revisions"] == {
        "info": current(w, "info"),
        "analysis_ai": None,
        "analysis": None,
        "roadmap_ai": None,
    }
    assert list(technical["revisions"][0]) == [
        "id",
        "revision_number",
        "status",
        "author_name",
        "author_actor_type",
        "created_at",
        "content_hash",
    ]
    approval = view["approvals"]["analysis"]
    assert (approval["scope"], approval["decision"]) == ("analysis", "approved")
    assert "revisions_json" in approval


def test_the_documents_view_lists_the_twenty_newest_revisions() -> None:
    w = world()
    for number in range(22):
        info(w, f"Revision {number}")
    revisions = w.service.documents(BOARD_ID, LOOP)["documents"]["info"]["revisions"]
    assert [entry["revision_number"] for entry in revisions] == list(range(22, 2, -1))


def test_an_unknown_loop_is_not_found() -> None:
    with pytest.raises(NotFound) as caught:
        world().service.documents(BOARD_ID, "nope")
    assert caught.value.code == "loop_not_found"


def test_the_history_pages_newest_first_and_parses_each_payload() -> None:
    w = world()
    info(w)
    analysis(w)
    analysis(w)
    items, total = w.service.revision_history(BOARD_ID, LOOP, "analysis_ai", limit=1, offset=1)
    assert total == 2
    (entry,) = items
    assert entry["revision_number"] == 1
    assert entry["payload"] == ANALYSIS.model_dump()
    assert "payload_json" not in entry
    assert list(entry)[-2:] == ["created_at", "payload"]


def test_the_history_refuses_an_unknown_kind() -> None:
    with pytest.raises(ValidationFailure) as caught:
        world().service.revision_history(BOARD_ID, LOOP, "notes")
    assert caught.value.details == {
        "allowed": ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"]
    }


def test_the_context_carries_documents_the_plan_and_the_schemas() -> None:
    w = world()
    info(w, "Intent")
    context = w.service.context(BOARD_ID, LOOP)
    assert list(context) == [
        "loop_id",
        "loop_key",
        "loop_name",
        "goal",
        "stage",
        "documents",
        "plan",
        "labels",
        "schemas",
    ]
    # The board's label names: the areas a planned Ticket may name.
    assert context["labels"] == [label.name for label in w.state.labels.values()]
    document = context["documents"]["info"]
    assert document is not None
    assert (document["revision_number"], document["content"], document["payload"]) == (
        1,
        "Intent",
        None,
    )
    assert context["documents"]["analysis"] is None
    assert context["plan"] == {"plan_id": None, "revision_number": None, "phases": []}
    assert sorted(context.get("schemas", {})) == [
        "analysis",
        "analysis_brief",
        "qa",
        "roadmap",
        "roadmap_brief",
    ]


# --- Info ----------------------------------------------------------------------------------------


def test_info_is_written_as_a_new_current_revision_and_logged() -> None:
    w = world()
    info(w, "First")
    info(w, "Second")
    rows = [row for row in w.state.documents if row.kind == "info"]
    assert [(row.revision_number, row.is_current) for row in rows] == [(1, 0), (2, 1)]
    newest = rows[-1]
    assert (newest.content, newest.status) == ("Second", "ready_for_review")
    assert newest.created_at == STAMP
    assert newest.content_hash == content_hash("Second")
    assert json.loads(newest.provenance_json) == {"note": ""}
    assert (newest.author_actor_id, newest.author_name) == ("actor-1", "Ada")
    entry = w.state.activity[-1]
    assert (entry.action, json.loads(entry.changes_json)) == ("loop.info_revised", {"revision": 2})


@pytest.mark.parametrize("stage", ["draft", "analysis_review"])
def test_a_worker_may_write_info_while_the_loop_is_speculative(stage: str) -> None:
    w = world(stage)
    info(w, "Seed", actor=AGENT)
    assert w.state.documents[-1].author_actor_type == "agent"


@pytest.mark.parametrize("stage", ["planning", "ready", "in_progress"])
def test_info_is_a_persons_decision_once_the_loop_is_planned(stage: str) -> None:
    w = world(stage)
    with pytest.raises(Forbidden) as caught:
        info(w, actor=AGENT)
    assert caught.value.code == "human_action_required"
    assert caught.value.details == {"stage": stage, "action": "Editing Loop Info"}
    assert w.state.documents == []


def test_info_edited_from_an_older_revision_is_refused() -> None:
    w = world()
    info(w)
    first = current(w, "info")
    with pytest.raises(VersionConflict) as caught:
        w.service.save_info(
            HUMAN, BOARD_ID, LOOP, InfoRevisionWrite(content="x", expected_revision_id="old")
        )
    assert caught.value.code == "document_stale"
    assert caught.value.details == {"expected_revision_id": "old", "current_revision_id": first}
    w.service.save_info(
        HUMAN, BOARD_ID, LOOP, InfoRevisionWrite(content="y", expected_revision_id=first)
    )
    assert w.repos.documents.current(LOOP, "info") is not None


def test_info_needs_the_write_scope_and_a_writable_loop() -> None:
    w = world()
    reader = ActorContext(actor_id="r", actor_type="user", actor_name="R", scopes=frozenset())
    with pytest.raises(Forbidden):
        info(w, actor=reader)
    w.state.loops[LOOP] = w.loop.__replace__(completed_at=STAMP, stage="completed")
    with pytest.raises(Conflict) as caught:
        info(w)
    assert caught.value.code == "loop_read_only"


def test_changed_info_invalidates_every_approval_downstream_and_open_qa() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    review(w, "roadmap")
    w.state.loops[LOOP] = w.loop.__replace__(
        implementation_approval_id="impl", qa_approval_id="qa"
    )
    w.state.qa_cycles = {
        "open": qa_cycle_row("open", LOOP, 1, status="in_progress"),
        "done": qa_cycle_row("done", LOOP, 2, status="passed"),
    }
    info(w, "Changed intent")
    loop = w.loop
    assert (
        loop.analysis_approval_id,
        loop.roadmap_approval_id,
        loop.implementation_approval_id,
        loop.qa_approval_id,
    ) == (None, None, None, None)
    approved = [row.kind for row in w.state.documents if row.is_approved]
    assert approved == []
    assert (w.state.qa_cycles["open"].status, w.state.qa_cycles["done"].status) == (
        "superseded",
        "passed",
    )
    assert loop.stage == "replanning"


# --- candidates ----------------------------------------------------------------------------------


def test_an_analysis_candidate_writes_both_revisions_and_logs_them() -> None:
    w = world()
    info(w)
    w.service.submit_candidate(
        HUMAN,
        BOARD_ID,
        LOOP,
        CandidateSubmission(kind="analysis", analysis=ANALYSIS, provenance={"tool": "cli"}),
    )
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    human = w.repos.documents.current(LOOP, "analysis")
    assert technical is not None
    assert human is not None
    assert technical.payload_json == json.dumps(ANALYSIS.model_dump())
    structured = json.dumps(ANALYSIS.model_dump(), sort_keys=True)
    assert technical.content_hash == content_hash(technical.content + structured)
    assert technical.content.startswith("```json\n")
    assert technical.source_info_revision_id == current(w, "info")
    assert (human.payload_json, human.content) == (None, render_analysis(ANALYSIS))
    assert (human.source_analysis_ai_revision_id, human.source_info_revision_id) == (
        technical.id,
        current(w, "info"),
    )
    assert json.loads(human.provenance_json) == {"submitted": True, "rendered": True, "tool": "cli"}
    entry = w.state.activity[-1]
    assert (entry.action, json.loads(entry.changes_json)) == (
        "loop.analysis_candidate",
        {"analysis_ai_revision": 1, "analysis_revision": 1},
    )
    assert w.loop.stage == "analysis_review"


def test_a_candidate_needs_its_payload_and_the_generate_scope() -> None:
    w = world()
    info(w)
    for kind in ("analysis", "roadmap"):
        with pytest.raises(ValidationFailure):
            w.service.submit_candidate(HUMAN, BOARD_ID, LOOP, CandidateSubmission(kind=kind))
    writer = ActorContext(
        actor_id="w", actor_type="user", actor_name="W", scopes=frozenset({"loops:write"})
    )
    with pytest.raises(Forbidden):
        w.service.submit_candidate(
            writer, BOARD_ID, LOOP, CandidateSubmission(kind="analysis", analysis=ANALYSIS)
        )


def test_a_material_finding_needs_a_plain_language_explanation() -> None:
    w = world()
    info(w)
    risky = ANALYSIS.model_copy(
        update={
            "findings": [
                ANALYSIS.findings[0].model_copy(
                    update={"id": "F-09", "category": "security", "plain_language": "  "}
                )
            ]
        }
    )
    with pytest.raises(ValidationFailure) as caught:
        analysis(w, risky)
    assert caught.value.details == {"finding_ids": ["F-09"]}


def test_a_payload_over_the_size_limit_is_refused() -> None:
    w = world()
    info(w)
    huge = ANALYSIS.model_copy(update={"recommendation": "x" * (MAX_DOCUMENT_PAYLOAD + 1)})
    with pytest.raises(ValidationFailure) as caught:
        analysis(w, huge)
    assert (caught.value.code, caught.value.details) == (
        "payload_too_large",
        {"limit": MAX_DOCUMENT_PAYLOAD},
    )


def test_an_analysis_needs_current_info_or_a_named_info_revision() -> None:
    w = world()
    with pytest.raises(Conflict) as caught:
        analysis(w)
    assert (caught.value.code, caught.value.details) == ("document_stale", {"missing": "info"})
    w.service.submit_candidate(
        HUMAN,
        BOARD_ID,
        LOOP,
        CandidateSubmission(kind="analysis", analysis=ANALYSIS, source_info_revision_id="named"),
    )
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    assert technical is not None
    assert technical.source_info_revision_id == "named"


def test_a_roadmap_needs_a_current_approved_analysis() -> None:
    w = world()
    info(w)
    analysis(w)
    with pytest.raises(Conflict) as caught:
        roadmap(w)
    assert (caught.value.code, caught.value.details) == ("approval_required", {"scope": "analysis"})
    assert w.state.plans == {}


def test_a_roadmap_candidate_registers_its_plan_and_links_both_revisions() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    (plan,) = w.state.plans.values()
    technical = w.repos.documents.current(LOOP, "roadmap_ai")
    human = w.repos.documents.current(LOOP, "roadmap")
    assert technical is not None
    assert human is not None
    canonical = json.loads(plan.payload_json)
    assert technical.payload_json == plan.payload_json
    assert technical.content == "```json\n" + json.dumps(canonical, indent=2) + "\n```\n"
    assert (plan.roadmap_ai_revision_id, plan.roadmap_revision_id) == (technical.id, human.id)
    assert (technical.source_info_revision_id, technical.source_analysis_revision_id) == (
        current(w, "info"),
        current(w, "analysis"),
    )
    assert human.source_roadmap_ai_revision_id == technical.id
    assert json.loads(human.provenance_json) == {"plan_id": plan.id, "rendered": True}
    assert human.content.startswith("# RoadMap\n\nTwo phases\n")
    # The analysis approval stands; a new RoadMap only invalidates what follows it.
    assert w.loop.analysis_approval_id is not None
    entry = w.state.activity[-1]
    assert (entry.action, json.loads(entry.changes_json)) == (
        "loop.roadmap_candidate",
        {"plan_id": plan.id, "phases": 2},
    )


def _as_agent(w: World, kind: str) -> None:
    submission = (
        CandidateSubmission(kind="analysis", analysis=ANALYSIS)
        if kind == "analysis"
        else CandidateSubmission(kind="roadmap", plan=PLAN)
    )
    w.service.submit_candidate(AGENT, BOARD_ID, LOOP, submission)


def test_a_worker_never_replaces_an_approved_analysis_until_a_person_reopens_it() -> None:
    w = world()
    approved_analysis(w)
    before = len(w.state.documents)
    with pytest.raises(Forbidden) as refused:
        _as_agent(w, "analysis")
    assert (refused.value.code, refused.value.details) == (
        "human_action_required",
        {"stage": "planning", "action": "Replacing an approved analysis"},
    )
    assert len(w.state.documents) == before
    # Requested changes reopen it for the worker.
    review(w, "analysis", decision="changes_requested")
    _as_agent(w, "analysis")
    assert len(w.state.documents) == before + 2
    # So does a reset of an approved one.
    review(w, "analysis")
    w.service.reset(HUMAN, BOARD_ID, LOOP, "analysis", ScopeResetRequest(version=w.loop.version))
    _as_agent(w, "analysis")
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    assert technical is not None
    assert technical.author_actor_id == AGENT.actor_id


def test_a_worker_may_replace_an_approval_that_changed_info_made_stale() -> None:
    w = world()
    approved_analysis(w)
    info(w, "Users must confirm by e-mail.")
    _as_agent(w, "analysis")
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    assert technical is not None
    assert (technical.author_actor_id, technical.source_info_revision_id) == (
        AGENT.actor_id,
        current(w, "info"),
    )


def test_a_worker_never_replaces_an_approved_roadmap_and_a_person_always_may() -> None:
    w = world()
    approved_analysis(w)
    _as_agent(w, "roadmap")
    review(w, "roadmap")
    with pytest.raises(Forbidden) as refused:
        _as_agent(w, "roadmap")
    assert refused.value.details == {"stage": "ready", "action": "Replacing an approved RoadMap"}
    with pytest.raises(Forbidden):
        _as_agent(w, "analysis")
    # The rule is about who decides, so a person is never refused on that ground.
    roadmap(w)
    analysis(w)
    assert len(w.state.plans) == 2


def test_a_candidate_written_from_an_older_revision_is_refused_as_stale() -> None:
    w = world()
    info(w)
    first_info = current(w, "info")
    info(w, "Users must confirm by e-mail.")
    with pytest.raises(VersionConflict) as caught:
        w.service.submit_candidate(
            AGENT,
            BOARD_ID,
            LOOP,
            CandidateSubmission(
                kind="analysis", analysis=ANALYSIS, expected_info_revision_id=first_info
            ),
        )
    assert (caught.value.code, caught.value.details) == (
        "document_stale",
        {
            "kind": "info",
            "expected_revision_id": first_info,
            "current_revision_id": current(w, "info"),
        },
    )
    w.service.submit_candidate(
        AGENT,
        BOARD_ID,
        LOOP,
        CandidateSubmission(
            kind="analysis", analysis=ANALYSIS, expected_info_revision_id=current(w, "info")
        ),
    )
    review(w, "analysis")
    with pytest.raises(VersionConflict) as planned:
        w.service.submit_candidate(
            AGENT,
            BOARD_ID,
            LOOP,
            CandidateSubmission(kind="roadmap", plan=PLAN, expected_analysis_revision_id="old"),
        )
    assert planned.value.details == {
        "kind": "analysis_ai",
        "expected_revision_id": "old",
        "current_revision_id": current(w, "analysis_ai"),
    }
    assert w.state.plans == {}


# --- reviews -------------------------------------------------------------------------------------


def test_a_review_is_a_persons_decision_and_needs_the_review_scope() -> None:
    w = world()
    approved_analysis(w)
    request = ApprovalRequest(decision="approved", version=w.loop.version)
    with pytest.raises(Forbidden) as caught:
        w.service.review(AGENT, BOARD_ID, LOOP, "analysis", request)
    assert caught.value.code == "human_action_required"
    writer = ActorContext(actor_id="w", actor_type="user", actor_name="W", scopes=frozenset())
    with pytest.raises(Forbidden):
        w.service.review(writer, BOARD_ID, LOOP, "analysis", request)
    with pytest.raises(ValidationFailure):
        w.service.review(HUMAN, BOARD_ID, LOOP, "qa", request)


def test_a_review_of_an_older_loop_version_is_refused() -> None:
    w = world()
    info(w)
    analysis(w)
    with pytest.raises(VersionConflict) as caught:
        w.service.review(
            HUMAN, BOARD_ID, LOOP, "analysis", ApprovalRequest(decision="approved", version=9)
        )
    assert caught.value.details == {"expected_version": 9, "current_version": 1}


def test_a_review_needs_every_document_of_its_scope() -> None:
    w = world()
    approved_analysis(w)
    with pytest.raises(Conflict) as caught:
        review(w, "roadmap")
    assert caught.value.message == "Roadmap Ai is missing"
    assert caught.value.code == "document_stale"
    assert caught.value.details == {"missing": "roadmap_ai"}


def test_a_review_binds_to_the_revisions_the_reviewer_saw() -> None:
    w = world()
    info(w)
    analysis(w)
    with pytest.raises(ValidationFailure) as outside:
        review(w, "analysis", revisions={"roadmap": "x"})
    assert outside.value.details == {"kind": "roadmap"}
    with pytest.raises(Conflict) as changed:
        review(w, "analysis", revisions={"analysis": "older"})
    assert (changed.value.code, changed.value.details) == (
        "document_stale",
        {"kind": "analysis", "expected": current(w, "analysis")},
    )
    review(w, "analysis", revisions={"analysis": current(w, "analysis")})
    assert w.loop.analysis_approval_id is not None


def test_an_approval_records_the_exact_revisions_and_their_hashes() -> None:
    w = world()
    info(w)
    analysis(w)
    version = w.loop.version
    result = review(w, "analysis", feedback="Fine")
    approval = w.state.approvals[-1]
    expected = {kind: current(w, kind) for kind in ("info", "analysis_ai", "analysis")}
    assert json.loads(approval.revisions_json) == expected
    hashes = json.loads(approval.source_hashes_json)
    assert list(hashes) == ["info", "analysis_ai", "analysis"]
    assert (approval.loop_version, approval.feedback) == (version, "Fine")
    assert approval.reviewer_name == "Ada"
    assert list(result)[-2:] == ["revisions", "source_hashes"]
    assert "revisions_json" not in result
    approved = {row.kind for row in w.state.documents if row.is_approved}
    assert approved == {"analysis_ai", "analysis"}
    assert all(
        row.status == "approved"
        for row in w.state.documents
        if row.kind != "info" and row.is_current
    )
    loop = w.loop
    assert (loop.analysis_approval_id, loop.version) == (approval.id, version + 1)
    assert loop.stage == "planning"
    entry = w.state.activity[-1]
    assert (entry.action, json.loads(entry.changes_json)) == (
        "loop.analysis_reviewed",
        {"decision": "approved", "approval_id": approval.id},
    )


def test_a_new_decision_supersedes_the_scopes_earlier_ones() -> None:
    w = world()
    info(w)
    analysis(w)
    review(w, "analysis", decision="changes_requested")
    review(w, "analysis")
    first, second = w.state.approvals
    assert (first.superseded_at, second.superseded_at) == (STAMP, None)


def test_requested_changes_keep_the_text_and_mark_it() -> None:
    w = world()
    info(w)
    analysis(w)
    review(w, "analysis", decision="changes_requested", feedback="More")
    statuses = {row.kind: (row.status, row.is_approved) for row in w.state.documents}
    assert statuses["analysis"] == ("changes_requested", 0)
    assert statuses["analysis_ai"] == ("changes_requested", 0)
    assert statuses["info"] == ("ready_for_review", 0)
    assert w.loop.analysis_approval_id is None
    view = w.service.documents(BOARD_ID, LOOP)
    assert view["documents"]["analysis"]["state"] == "changes_requested"


def test_nothing_empty_can_be_approved() -> None:
    w = world()
    info(w)
    analysis(w)
    w.service.reset(HUMAN, BOARD_ID, LOOP, "analysis", ScopeResetRequest(version=w.loop.version))
    with pytest.raises(Conflict) as caught:
        review(w, "analysis")
    assert (caught.value.code, caught.value.details) == ("document_empty", {"kind": "analysis_ai"})


def test_approving_a_roadmap_publishes_its_plan() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    review(w, "roadmap")
    (plan,) = w.state.plans.values()
    assert (plan.status, plan.approval_id) == ("active", w.loop.roadmap_approval_id)
    assert sorted(card.id for card in w.state.cards.values()) == [T1, T2]
    assert (w.loop.current_plan_id, w.loop.stage) == (plan.id, "ready")
    # Each card carries its Ticket's face for people, copied with the summary.
    card = w.state.cards[T1]
    assert (card.summary, json.loads(card.face)["steps"]) == (FACE["summary"], FACE["steps"])


def test_a_roadmap_without_a_registered_plan_cannot_be_approved() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    technical = w.repos.documents.current(LOOP, "roadmap_ai")
    assert technical is not None
    for provenance in ("{}", '{"plan_id": ""}', '{"plan_id": 7}'):
        w.state.documents = [
            row.__replace__(provenance_json=provenance) if row.id == technical.id else row
            for row in w.state.documents
        ]
        with pytest.raises(Conflict) as caught:
            review(w, "roadmap")
        assert caught.value.code == "plan_change_required"
    w.state.documents = [
        row.__replace__(provenance_json="[]") if row.id == technical.id else row
        for row in w.state.documents
    ]
    with pytest.raises(AttributeError):
        review(w, "roadmap")
    assert all(plan.status == "draft" for plan in w.state.plans.values())


# --- the brief for people ------------------------------------------------------------------------


@dataclass(slots=True)
class HumanViews:
    """The composition root's ``start_human_view``, recorded: who asked, for which Loop and
    scope."""

    calls: list[tuple[str, str, str, str]] = field(
        default_factory=list[tuple[str, str, str, str]]
    )

    def __call__(
        self, actor: ActorContext, board_id: str, loop_id: str, kind: str
    ) -> HumanViewStart:
        self.calls.append((actor.actor_id, board_id, loop_id, kind))
        return {"status": "queued", "run_id": "run-9"}


def human_run(status: str, purpose: str = "analysis_human") -> LoopGenerationRunsRow:
    return LoopGenerationRunsRow(
        id="run-9",
        loop_id=LOOP,
        purpose=purpose,
        status=status,
        input_json="{}",
        input_hash="",
        source_revisions_json="{}",
        output_json="{}",
        error_code=None,
        error_message=None,
        attempts=0,
        agent_id="alpha",
        agent_name="Alpha",
        model=None,
        role_snapshot_json="{}",
        usage_json="{}",
        created_by_actor_id="actor-1",
        created_by_actor_type="user",
        created_at=STAMP,
        started_at=None,
        finished_at=None,
        phase=None,
        trace_json="[]",
    )


BRIEF = HumanBrief.model_validate(
    {
        **SIGN,
        "pros": [{"text": "The sign-in can be extended.", "finding_ids": ["F-01"]}],
        "verdict": "yes",
        "verdict_reason": "Nothing stands in the way.",
        "summary": "People confirm their address by e-mail.",
        "recommendation": "Go ahead.",
    }
)
ROADMAP_BRIEF = RoadmapBrief.model_validate(
    {
        "order": [
            {"phase_id": P1, "what_happens": "The data is prepared.", "done_when": "Ready."},
            {"phase_id": P2, "what_happens": "People confirm.", "done_when": "Signed off."},
        ],
        "your_part": [{"text": "Sign the legal text.", "phase_ids": [P2], "ticket_ids": [T2]}],
        "summary": "Two Phases, the second waits for the first.",
    }
)


def brief_for(kind: str, **fields: object) -> BriefWrite:
    return BriefWrite.model_validate(
        {"kind": kind, "brief": BRIEF if kind == "analysis" else ROADMAP_BRIEF, **fields}
    )


def test_a_candidate_without_a_brief_is_handed_on_to_be_written_for_people() -> None:
    w = world()
    info(w)
    views = HumanViews()
    w.service.human_view = views
    view = w.service.submit_candidate(
        HUMAN, BOARD_ID, LOOP, CandidateSubmission(kind="analysis", analysis=ANALYSIS)
    )
    assert view.get("human_view") == {"status": "queued", "run_id": "run-9"}
    assert views.calls == [("actor-1", BOARD_ID, LOOP, "analysis")]
    # The rendered view says what it is until somebody writes the brief.
    analysis_view = view["documents"]["analysis"]
    assert analysis_view["current_provenance"] == {"submitted": True, "rendered": True}
    review(w, "analysis")
    roadmap(w)
    assert views.calls[1:] == [("actor-1", BOARD_ID, LOOP, "roadmap")]
    rendered = w.service.documents(BOARD_ID, LOOP)["documents"]["roadmap"]
    assert rendered["current_provenance"].get("rendered") is True


def test_without_a_writer_the_rendered_view_stays_and_the_answer_says_so() -> None:
    w = world()
    info(w)
    view = w.service.submit_candidate(
        HUMAN, BOARD_ID, LOOP, CandidateSubmission(kind="analysis", analysis=ANALYSIS)
    )
    assert view.get("human_view") == {
        "status": "skipped",
        "run_id": None,
        "reason": "not configured",
    }


def test_a_candidate_with_its_brief_stores_it_and_asks_no_board_agent() -> None:
    w = world()
    info(w)
    views = HumanViews()
    w.service.human_view = views
    submission = CandidateSubmission(
        kind="analysis", analysis=ANALYSIS, analysis_brief=BRIEF, provenance={"through": "mcp"}
    )
    view = w.service.submit_candidate(AGENT, BOARD_ID, LOOP, submission)
    assert views.calls == []
    assert "human_view" not in view
    human = w.repos.documents.current(LOOP, "analysis")
    assert human is not None
    assert json.loads(human.payload_json or "{}") == BRIEF.model_dump()
    assert human.content.startswith("# Analysis\n\n**Can it be done?** Yes. Nothing stands")
    assert json.loads(human.provenance_json) == {
        "submitted": True,
        "through": "mcp",
        "written": True,
    }
    assert human.source_analysis_ai_revision_id == current(w, "analysis_ai")
    assert w.loop.stage == "analysis_review"


def test_a_candidates_brief_that_breaks_a_rule_stores_nothing() -> None:
    w = world()
    info(w)
    noisy = BRIEF.model_copy(update={"summary": "See app/auth.py [F-01]."})
    with pytest.raises(ValidationFailure) as refused:
        w.service.submit_candidate(
            AGENT,
            BOARD_ID,
            LOOP,
            CandidateSubmission(kind="analysis", analysis=ANALYSIS, analysis_brief=noisy),
        )
    assert refused.value.code == "brief_rejected"
    assert refused.value.details is not None
    assert refused.value.details["fields"] == ["summary"]
    with pytest.raises(ValidationFailure, match="never a roadmap_brief"):
        w.service.submit_candidate(
            AGENT,
            BOARD_ID,
            LOOP,
            CandidateSubmission(kind="analysis", analysis=ANALYSIS, roadmap_brief=ROADMAP_BRIEF),
        )


def test_a_roadmap_candidate_with_its_brief_covers_every_phase_and_the_persons_part() -> None:
    w = world()
    approved_analysis(w)
    submission = CandidateSubmission(kind="roadmap", plan=PLAN, roadmap_brief=ROADMAP_BRIEF)
    w.service.submit_candidate(AGENT, BOARD_ID, LOOP, submission)
    human = w.repos.documents.current(LOOP, "roadmap")
    assert human is not None
    (plan,) = w.state.plans.values()
    assert json.loads(human.provenance_json) == {"plan_id": plan.id, "written": True}
    assert "### Phase 2 — Sign-in" in human.content
    assert plan.roadmap_revision_id == human.id
    partial = ROADMAP_BRIEF.model_copy(update={"your_part": []})
    with pytest.raises(ValidationFailure) as refused:
        w.service.submit_candidate(
            AGENT,
            BOARD_ID,
            LOOP,
            CandidateSubmission(kind="roadmap", plan=PLAN, roadmap_brief=partial),
        )
    assert refused.value.details is not None
    assert refused.value.details["missing_ids"] == [T2]


def test_write_brief_rewrites_the_brief_of_the_current_technical_revision() -> None:
    w = world()
    info(w)
    analysis(w)
    technical = current(w, "analysis_ai")
    view = w.service.write_brief(
        AGENT, BOARD_ID, LOOP, brief_for("analysis", expected_revision_id=technical), through="mcp"
    )
    written = view["documents"]["analysis"]
    assert written["current_provenance"] == {
        "author": "Bot",
        "actor_id": "agent-1",
        "through": "mcp",
        "written": True,
    }
    assert written["current_payload"] == BRIEF.model_dump()
    assert written["source_revisions"].get("analysis_ai") == technical
    assert w.state.activity[-1].action == "loop.analysis_brief_written"
    with pytest.raises(VersionConflict) as stale:
        w.service.write_brief(
            AGENT, BOARD_ID, LOOP, brief_for("analysis", expected_revision_id="old"), through="mcp"
        )
    assert stale.value.code == "document_stale"
    with pytest.raises(ValidationFailure, match="analysis brief schema"):
        w.service.write_brief(
            AGENT,
            BOARD_ID,
            LOOP,
            BriefWrite(kind="analysis", brief=ROADMAP_BRIEF),
            through="mcp",
        )


def test_a_brief_needs_a_technical_revision_and_the_generate_scope() -> None:
    w = world()
    info(w)
    with pytest.raises(Conflict) as empty:
        w.service.write_brief(HUMAN, BOARD_ID, LOOP, brief_for("roadmap"), through="api")
    assert (empty.value.code, empty.value.details) == ("document_empty", {"kind": "roadmap_ai"})
    reader = ActorContext(
        actor_id="r", actor_type="agent", actor_name="R", scopes=frozenset({"loops:read"})
    )
    with pytest.raises(Forbidden):
        w.service.write_brief(reader, BOARD_ID, LOOP, brief_for("analysis"), through="mcp")


def test_over_an_approval_a_token_is_refused_and_a_person_is_not() -> None:
    w = world()
    approved_analysis(w)
    with pytest.raises(Forbidden) as refused:
        w.service.write_brief(AGENT, BOARD_ID, LOOP, brief_for("analysis"), through="mcp")
    assert refused.value.code == "human_action_required"
    w.service.write_brief(HUMAN, BOARD_ID, LOOP, brief_for("analysis"), through="api")
    view = w.service.documents(BOARD_ID, LOOP)["documents"]["analysis"]
    # Writing a brief is not approving it: the person reviews the new pair again.
    assert view["current_provenance"]["through"] == "api"
    assert w.loop.analysis_approval_id is None
    assert w.loop.stage == "analysis_review"


def test_a_written_brief_becomes_the_current_view_from_the_current_sources() -> None:
    w = world()
    info(w)
    analysis(w)
    with w.store.writer(BOARD_ID) as repos:
        stored = w.service.store_written_brief(
            repos, w.loop, BRIEF, AGENT, run_id="run-9", provenance={"model": "m"}
        )
    human = w.repos.documents.current(LOOP, "analysis")
    assert human is not None
    assert stored == {"analysis": human.id}
    assert (human.generation_run_id, human.revision_number) == ("run-9", 2)
    assert (human.source_analysis_ai_revision_id, human.source_info_revision_id) == (
        current(w, "analysis_ai"),
        current(w, "info"),
    )
    assert json.loads(human.provenance_json) == {"model": "m", "written": True}
    state = w.service.documents(BOARD_ID, LOOP)["documents"]["analysis"]
    assert state["state"] == "ready_for_review"


def test_a_brief_is_never_written_without_a_technical_analysis() -> None:
    w = world()
    info(w)
    with pytest.raises(Conflict) as refused, w.store.writer(BOARD_ID) as repos:
        w.service.store_written_brief(repos, w.loop, BRIEF, AGENT, run_id="r", provenance={})
    assert refused.value.code == "document_empty"
    assert refused.value.details == {"kind": "analysis_ai"}


def test_the_analysis_is_not_approved_while_it_is_being_written_for_people() -> None:
    w = world()
    info(w)
    analysis(w)
    w.state.generation_runs = {"run-9": human_run("running")}
    with pytest.raises(Conflict) as refused:
        review(w, "analysis")
    assert (refused.value.code, refused.value.details) == (
        "generation_in_progress",
        {"purpose": "analysis_human", "run_id": "run-9"},
    )
    assert w.loop.analysis_approval_id is None
    w.state.generation_runs = {"run-9": human_run("failed")}
    review(w, "analysis")
    assert w.loop.analysis_approval_id is not None


def test_the_roadmap_is_not_approved_while_its_brief_is_being_written() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    w.state.generation_runs = {"run-9": human_run("queued", "roadmap_human")}
    with pytest.raises(Conflict) as refused:
        review(w, "roadmap")
    assert refused.value.details == {"purpose": "roadmap_human", "run_id": "run-9"}


# --- resets --------------------------------------------------------------------------------------


def test_a_reset_is_a_persons_decision_for_a_known_scope() -> None:
    w = world()
    approved_analysis(w)
    request = ScopeResetRequest(version=w.loop.version)
    with pytest.raises(Forbidden) as caught:
        w.service.reset(AGENT, BOARD_ID, LOOP, "analysis", request)
    assert caught.value.code == "human_action_required"
    with pytest.raises(ValidationFailure) as unknown:
        w.service.reset(HUMAN, BOARD_ID, LOOP, "info", request)
    assert unknown.value.details == {"allowed": ["analysis", "roadmap"]}
    with pytest.raises(VersionConflict):
        w.service.reset(HUMAN, BOARD_ID, LOOP, "analysis", ScopeResetRequest(version=99))


def test_there_must_be_text_or_an_approval_to_reset() -> None:
    w = world()
    info(w)
    with pytest.raises(Conflict) as caught:
        w.service.reset(HUMAN, BOARD_ID, LOOP, "roadmap", ScopeResetRequest(version=1))
    assert (caught.value.code, caught.value.details) == ("nothing_to_reset", {"scope": "roadmap"})


def test_a_reset_supersedes_the_approval_and_leaves_an_empty_chained_draft() -> None:
    w = world()
    approved_analysis(w)
    approval_id = w.loop.analysis_approval_id
    version = w.loop.version
    result = w.service.reset(
        HUMAN, BOARD_ID, LOOP, "analysis", ScopeResetRequest(version=version)
    )
    assert result == {
        "scope": "analysis",
        "approval_id": approval_id,
        "cleared": ["analysis_ai", "analysis"],
        "version": version + 1,
    }
    approval = w.repos.approvals.get(approval_id or "")
    assert approval is not None
    assert approval.superseded_at == STAMP
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    human = w.repos.documents.current(LOOP, "analysis")
    assert technical is not None
    assert human is not None
    assert (technical.content, technical.status, technical.revision_number) == ("", "draft", 2)
    assert technical.source_info_revision_id == current(w, "info")
    assert human.source_analysis_ai_revision_id == technical.id
    assert json.loads(human.provenance_json) == {
        "reset_by": "actor-1",
        "reset_approval_id": approval_id,
    }
    assert w.loop.analysis_approval_id is None
    entry = w.state.activity[-1]
    assert (entry.action, json.loads(entry.changes_json)) == (
        "loop.analysis_reset",
        {"approval_id": approval_id, "cleared": ["analysis_ai", "analysis"]},
    )


def test_a_draft_that_was_never_approved_can_be_reset() -> None:
    w = world()
    approved_analysis(w)
    roadmap(w)
    result = w.service.reset(
        HUMAN, BOARD_ID, LOOP, "roadmap", ScopeResetRequest(version=w.loop.version)
    )
    assert result["approval_id"] is None
    technical = w.repos.documents.current(LOOP, "roadmap_ai")
    assert technical is not None
    assert (technical.source_analysis_ai_revision_id, technical.source_analysis_revision_id) == (
        current(w, "analysis_ai"),
        current(w, "analysis"),
    )
    # A RoadMap reset leaves the analysis approval standing.
    assert w.loop.analysis_approval_id is not None


# --- what a generation run stores ----------------------------------------------------------------


def test_a_generated_analysis_needs_info_and_is_stored_with_its_run() -> None:
    w = world()
    with pytest.raises(Conflict) as caught:
        w.service.store_generated_analysis(
            w.repos, w.loop, ANALYSIS, AGENT, run_id="run-1", provenance={}
        )
    assert (caught.value.code, caught.value.details) == ("document_stale", None)
    info(w)
    activity = len(w.state.activity)
    outputs = w.service.store_generated_analysis(
        w.repos, w.loop, ANALYSIS, AGENT, run_id="run-1", provenance={"model": "m"}
    )
    assert outputs == {"analysis_ai": current(w, "analysis_ai"), "analysis": current(w, "analysis")}
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    assert technical is not None
    assert (technical.generation_run_id, json.loads(technical.provenance_json)) == (
        "run-1",
        {"model": "m"},
    )
    assert len(w.state.activity) == activity
    assert w.loop.stage == "analysis_review"


def test_a_generated_roadmap_needs_an_approved_analysis_and_registers_its_plan() -> None:
    w = world()
    info(w)
    with pytest.raises(Conflict) as caught:
        w.service.store_generated_roadmap(
            w.repos, w.loop, PLAN, AGENT, run_id="run-2", provenance={}
        )
    assert (caught.value.code, caught.value.details) == ("approval_required", None)
    analysis(w)
    review(w, "analysis")
    outputs = w.service.store_generated_roadmap(
        w.repos, w.loop, PLAN, AGENT, run_id="run-2", provenance={"model": "m"}
    )
    (plan,) = w.state.plans.values()
    assert outputs == {
        "plan_id": plan.id,
        "roadmap_ai": current(w, "roadmap_ai"),
        "roadmap": current(w, "roadmap"),
    }
    human = w.repos.documents.current(LOOP, "roadmap")
    assert human is not None
    assert json.loads(human.provenance_json) == {
        "plan_id": plan.id,
        "model": "m",
        "rendered": True,
    }
    assert human.generation_run_id == "run-2"
    assert plan.roadmap_ai_revision_id == outputs["roadmap_ai"]
    assert plan.roadmap_revision_id == human.id


# --- rendering -----------------------------------------------------------------------------------


def test_the_roadmap_renders_phases_gates_human_tickets_and_prerequisites() -> None:
    w = world()
    approved_analysis(w)
    gate = PlanPayload.model_validate(
        {
            "summary": "",
            "phases": [
                {
                    "id": P1,
                    "number": 1,
                    "name": "Database",
                    "objective": "Store",
                    "narrative": "First the data.",
                    "entry_conditions": ["db up"],
                    "exit_conditions": ["tests"],
                    "tickets": [
                        {"id": T1, "title": "Gate", "execution_mode": "pre_phase_gate"},
                    ],
                },
                {
                    "id": P2,
                    "number": 2,
                    "name": "Sign-in",
                    "prerequisite_phase_ids": [P1],
                    "prerequisite_ticket_ids": [T1],
                    "tickets": [
                        {
                            "id": T2,
                            "title": "Confirm",
                            "objective": "Why",
                            "note": "Careful",
                            "required_actor": "human",
                            "human_action_reason": "Legal",
                            "human_instructions": "Sign",
                            "prerequisite_ticket_ids": [T1],
                            "prerequisite_phase_ids": [P1],
                            "acceptance_criteria": ["a", "b"],
                        }
                    ],
                },
            ],
        }
    )
    draft = LoopPlanService(clock=lambda: NOW).register_draft(w.repos, w.loop, gate, HUMAN)
    text = render_roadmap(draft["payload"])
    gate_key = draft["payload"]["phases"][0]["tickets"][0]["key"]
    human_key = draft["payload"]["phases"][1]["tickets"][0]["key"]
    assert text == (
        "# RoadMap\n\n"
        "## Phase 1 — Database\n\nStore\n\nFirst the data.\n\n"
        "**Before it can start:**\n- db up\n\n**Done when:**\n- tests\n\n"
        f"**Tickets**\n\n- `{gate_key}` Gate\n"
        "  - This is a gate: the Phase cannot start until it is confirmed.\n\n"
        "## Phase 2 — Sign-in\n\n"
        f"**Starts after:** Phase 1 (Database), Ticket {gate_key}\n\n"
        f"**Tickets**\n\n- `{human_key}` Confirm — **Human action required**\n"
        "  - Why: Why\n  - Careful\n  - Why a human is needed: Legal\n"
        "  - What you must do: Sign\n"
        f"  - Can be done after: Ticket {gate_key}, Phase 1\n"
        "  - Accepted when: a; b\n\n"
        "---\n\nGenerated from the validated structured plan; the plan is authoritative.\n"
    )


def test_the_analysis_renders_its_sections_and_traceability() -> None:
    text = render_analysis(
        ANALYSIS.model_copy(
            update={
                "scope": ["sign-up"],
                "non_goals": ["SMS"],
                "assumptions": ["mail"],
                "open_questions": ["who?"],
                "options": ["a"],
                "verification": ["e2e"],
                "sources": ["docs"],
                "repository_revision": "abc",
            }
        )
    )
    for heading in (
        "## What this Loop sets out to achieve",
        "**In scope**",
        "**Not in scope**",
        "## What was found",
        "## Assumptions",
        "## Open questions",
        "## Options considered",
        "## Recommended direction",
        "## How success can be checked",
        "## Traceability",
        "**Sources**",
    ):
        assert heading in text
    assert "- **Reuse auth** — Extend sign-in." in text
    assert "- `F-01` (reuse) Reuse auth: auth.py" in text
    assert text.endswith("Baseline revision: `abc`\n")
    empty = render_analysis(AnalysisPayload(outcome=""))
    assert "Not described." in empty
    assert "No findings were recorded." in empty
