"""LoopService and the Loop rules every Loop service shares, on an in-memory board.

The stage, staleness and approval rules are pure functions over typed rows; the service runs its
real code against the typed fakes in ``tests/unit/fakes`` (repositories, unit of work, registry
checks, plan views), with a fixed clock and id source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure, VersionConflict
from app.db.generated.board import BoardLoopDefaultsRow, IdempotencyRecordsRow, LoopsRow
from app.schemas.loops import HumanConfirmation, LoopCancel, LoopCreate, LoopUpdate
from app.services.cards import CardService
from app.services.loops import (
    DocumentSlots,
    LoopService,
    TicketReader,
    analysis_approved,
    compute_stage,
    document_slots,
    document_state,
    ensure_execution_allowed,
    ensure_writable,
    latest_approvals,
    loop_warnings,
    qa_summary,
    refresh_stage,
    roadmap_approved,
    stale_reasons,
)
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    approval_row,
    card_row,
    document_row,
    list_row,
    loop_row,
    phase_row,
    plan_item_row,
    plan_row,
    qa_cycle_row,
)
from tests.unit.fakes.plans import BLOCKER, FakePlanViews, plan_views, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
SCOPES = frozenset({"loops:read", "loops:write", "cards:read", "cards:write"})
HUMAN = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES, request_id="req-1"
)
AGENT = ActorContext(actor_id="agent-1", actor_type="agent", actor_name="Bot", scopes=SCOPES)
READER = ActorContext(
    actor_id="actor-2", actor_type="user", actor_name="Reader", scopes=frozenset({"loops:read"})
)


def card_service_is_a_ticket_reader(service: CardService) -> TicketReader:
    """Never called: pyright proves that the CardService wired in Services fits TicketReader."""
    return service


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    views: FakePlanViews
    clock: Clock
    service: LoopService


def world(settings: Settings, *loops: LoopsRow) -> World:
    state = BoardState()
    state.loops = {loop.id: loop for loop in loops}
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    views = FakePlanViews()
    clock = Clock()
    ids = Ids()
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=plan_views(views),
        clock=clock,
        new_id=ids,
    )
    service = LoopService(
        settings, checks, store, plans=plan_views(views), tickets=cards, clock=clock, new_id=ids
    )
    return World(state, store, checks, views, clock, service)


def repos(state: BoardState) -> FakeBoardRepositories:
    return FakeBoardRepositories(state)


# --- documents, approvals and staleness -----------------------------------------------------------


def test_each_kind_gets_its_current_and_approved_revision_and_every_kind_has_a_slot() -> None:
    first = document_row("i1", LOOP, "info", revision=1, current=False, approved=True)
    second = document_row("i2", LOOP, "info", revision=2, current=True)
    slots = document_slots([first, second])
    assert sorted(slots) == sorted(["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"])
    assert slots["info"].current == second
    assert slots["info"].approved == first
    assert slots["analysis"].current is None


def test_the_latest_unsuperseded_decision_of_each_scope_counts() -> None:
    newest_first = [
        approval_row("a3", LOOP, "analysis", superseded_at=STAMP),
        approval_row("a2", LOOP, "analysis", decision="changes_requested"),
        approval_row("a1", LOOP, "analysis"),
        approval_row("r1", LOOP, "roadmap", superseded_at=""),
    ]
    latest = latest_approvals(newest_first)
    assert {scope: row.id for scope, row in latest.items()} == {"analysis": "a2", "roadmap": "r1"}


def _chain() -> list[str]:
    return ["info-1", "ai-1", "an-1", "rai-1", "rm-1"]


def _documents(**overrides: str | None) -> DocumentSlots:
    """A consistent chain: each document was written from the current one upstream of it."""
    sources = {"ai": "info-1", "an": "ai-1", "rai_info": "info-1", "rai_ai": "ai-1"}
    sources |= {"rai_an": "an-1", "rm": "rai-1"}
    sources |= {key: value for key, value in overrides.items() if value is not None}
    rows = [
        document_row("info-1", LOOP, "info"),
        document_row("ai-1", LOOP, "analysis_ai", info=sources["ai"]),
        document_row("an-1", LOOP, "analysis", analysis_ai=sources["an"]),
        document_row(
            "rai-1",
            LOOP,
            "roadmap_ai",
            info=sources["rai_info"],
            analysis_ai=sources["rai_ai"],
            analysis=sources["rai_an"],
        ),
        document_row("rm-1", LOOP, "roadmap", roadmap_ai=sources["rm"]),
    ]
    missing = {key for key, value in overrides.items() if value is None}
    return document_slots(row for row in rows if row.id not in missing)


def test_a_consistent_chain_is_not_stale() -> None:
    assert all(not reasons for reasons in stale_reasons(_documents(), {}).values())


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ai": "info-0"}, {"analysis_ai": ["info_changed"], "analysis": ["upstream_stale"]}),
        ({"info-1": None}, {"analysis_ai": ["info_missing"], "analysis": ["upstream_stale"]}),
        ({"an": "ai-0"}, {"analysis": ["analysis_ai_changed"]}),
        ({"ai-1": None}, {"analysis": ["analysis_ai_missing"]}),
        ({"ai": "info-0", "an-1": None}, {"analysis_ai": ["info_changed"], "analysis": []}),
    ],
)
def test_a_changed_or_missing_input_makes_the_analysis_and_everything_downstream_stale(
    overrides: dict[str, str | None], expected: dict[str, list[str]]
) -> None:
    reasons = stale_reasons(_documents(**overrides), {})
    for kind, values in expected.items():
        assert reasons[kind] == values
    assert "upstream_stale" in reasons["roadmap_ai"]
    assert "upstream_stale" in reasons["roadmap"]


def test_the_roadmap_names_each_input_it_lost_or_that_changed() -> None:
    reasons = stale_reasons(
        _documents(rai_info="info-0", rai_ai="ai-0", rai_an="an-0", rm="rai-0"), {}
    )
    assert reasons["roadmap_ai"] == ["info_changed", "analysis_ai_changed", "analysis_changed"]
    assert reasons["roadmap"] == ["roadmap_ai_changed"]
    gone = stale_reasons(_documents(**{"rai-1": None}), {})
    assert gone["roadmap"] == ["roadmap_ai_missing"]


def test_a_roadmap_without_its_inputs_names_each_missing_one() -> None:
    slots = document_slots([document_row("rai-1", LOOP, "roadmap_ai")])
    assert stale_reasons(slots, {})["roadmap_ai"] == [
        "info_missing",
        "analysis_ai_missing",
        "analysis_missing",
    ]


def test_an_approval_of_other_revisions_is_superseded_kind_by_kind() -> None:
    reviewed = json.dumps({"info": "info-1", "analysis_ai": "ai-0", "analysis": "an-1"})
    approvals = latest_approvals([approval_row("a", LOOP, "analysis", revisions_json=reviewed)])
    reasons = stale_reasons(_documents(), approvals)
    assert reasons["analysis_ai"] == ["approval_superseded"]
    assert reasons["info"] == []
    assert reasons["analysis"] == []
    roadmap = json.dumps({"info": "info-1", "analysis_ai": "ai-1", "analysis": "an-1"})
    approvals = latest_approvals([approval_row("r", LOOP, "roadmap", revisions_json=roadmap)])
    reasons = stale_reasons(_documents(), approvals)
    assert reasons["roadmap_ai"] == ["approval_superseded"]
    assert reasons["roadmap"] == ["approval_superseded"]


def test_an_approval_does_not_supersede_a_document_that_is_gone() -> None:
    reviewed = json.dumps({"info": "info-1", "analysis_ai": "ai-1", "analysis": "an-1"})
    approvals = latest_approvals([approval_row("a", LOOP, "analysis", revisions_json=reviewed)])
    reasons = stale_reasons(_documents(**{"an-1": None}), approvals)
    assert reasons["analysis"] == []
    assert reasons["info"] == []


def test_a_decision_other_than_approved_supersedes_nothing() -> None:
    approvals = latest_approvals(
        [approval_row("a", LOOP, "analysis", decision="changes_requested")]
    )
    assert all(not reasons for reasons in stale_reasons(_documents(), approvals).values())


@pytest.mark.parametrize("raw", ["not json", "null"])
def test_unreadable_reviewed_revisions_review_nothing(raw: str) -> None:
    approvals = latest_approvals([approval_row("a", LOOP, "analysis", revisions_json=raw)])
    reasons = stale_reasons(_documents(), approvals)
    assert reasons["info"] == ["approval_superseded"]


def test_reviewed_revisions_that_are_not_an_object_fail_as_reading_a_key_always_did() -> None:
    approvals = latest_approvals([approval_row("a", LOOP, "analysis", revisions_json="[1]")])
    with pytest.raises(AttributeError):
        stale_reasons(_documents(), approvals)


def _all_reviewed() -> str:
    return json.dumps(
        dict(
            zip(["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"], _chain(), strict=True)
        )
    )


def test_analysis_and_roadmap_are_approved_only_when_current_complete_and_not_stale() -> None:
    documents = _documents()
    reviewed = _all_reviewed()
    approvals = latest_approvals(
        [
            approval_row("a", LOOP, "analysis", revisions_json=reviewed),
            approval_row("r", LOOP, "roadmap", revisions_json=reviewed),
        ]
    )
    stale = stale_reasons(documents, approvals)
    assert analysis_approved(documents, approvals, stale)
    assert roadmap_approved(documents, approvals, stale)
    assert not analysis_approved(documents, {}, stale)
    assert not roadmap_approved(documents, {}, stale)
    stale_info = {**stale, "info": ["approval_superseded"]}
    assert not analysis_approved(documents, approvals, stale_info)
    stale_roadmap = {**stale, "roadmap": ["roadmap_ai_changed"]}
    assert analysis_approved(documents, approvals, stale_roadmap)
    assert not roadmap_approved(documents, approvals, stale_roadmap)
    partial = _documents(**{"rm-1": None})
    assert not roadmap_approved(partial, approvals, stale_reasons(partial, approvals))
    no_info = _documents(**{"info-1": None})
    changes = latest_approvals(
        [approval_row("a", LOOP, "analysis", decision="changes_requested", revisions_json=reviewed)]
    )
    assert not analysis_approved(no_info, changes, {})


# --- the stage ------------------------------------------------------------------------------------


def _stage(
    loop: LoopsRow,
    documents: DocumentSlots,
    *scopes: str,
    plan: bool = False,
    done: int = 0,
) -> str:
    reviewed = _all_reviewed()
    approvals = latest_approvals(
        approval_row(scope, LOOP, scope, revisions_json=reviewed) for scope in scopes
    )
    stale = stale_reasons(documents, approvals)
    return compute_stage(loop, documents, approvals, stale, has_active_plan=plan, tickets_done=done)


def test_completion_and_cancellation_are_recorded_and_win() -> None:
    assert _stage(loop_row(LOOP, completed_at=STAMP), _documents()) == "completed"
    assert _stage(loop_row(LOOP, cancelled_at=STAMP), _documents()) == "cancelled"


def test_the_stage_follows_the_documents_before_a_plan_exists() -> None:
    loop = loop_row(LOOP, stage="draft")
    assert _stage(loop, document_slots(())) == "draft"
    assert _stage(loop, _documents(**{"an-1": None, "rm-1": None})) == "draft"
    assert _stage(loop, _documents(**{"rm-1": None})) == "analysis_review"
    roadmap_only = document_slots([document_row("rm-1", LOOP, "roadmap")])
    assert _stage(loop, roadmap_only) == "roadmap_review"
    assert _stage(loop, _documents(), "analysis") == "planning"
    assert _stage(loop, _documents(**{"rm-1": None, "rai-1": None}), "analysis") == "planning"


def test_an_active_plan_is_ready_until_a_ticket_is_done_and_replans_when_stale() -> None:
    loop = loop_row(LOOP)
    assert _stage(loop, _documents(), "analysis", "roadmap", plan=True) == "ready"
    assert _stage(loop, _documents(), "analysis", "roadmap", plan=True, done=2) == "in_progress"
    assert _stage(loop, _documents(), "analysis", plan=True, done=2) == "replanning"
    stale = _documents(ai="info-0")
    assert _stage(loop, stale, "analysis", "roadmap", plan=True) == "replanning"


def test_accepted_implementation_awaits_qa_unless_the_analysis_changed() -> None:
    accepted = loop_row(LOOP).__replace__(implementation_approval_id="impl")
    assert _stage(accepted, _documents(), "analysis", "roadmap", plan=True) == "awaiting_qa"
    assert _stage(accepted, _documents(), plan=True) == "replanning"
    qa_done = accepted.__replace__(qa_approval_id="qa")
    assert _stage(qa_done, _documents(), "analysis", "roadmap", plan=True) == "ready"


def test_a_column_named_done_never_completes_work(settings: Settings) -> None:
    loop = loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")
    w = world(settings, loop)
    w.state.lists = {"done": list_row("done", LOOP, 1024, name="Done")}
    w.state.cards = {"t": card_row("t", "done", LOOP).__replace__(kind="ticket")}
    _approve_everything(w.state)
    w.state.plans = {"plan-1": plan_row("plan-1", LOOP)}
    assert refresh_stage(repos(w.state), LOOP, now=STAMP) == "ready"
    w.state.cards["t"] = w.state.cards["t"].__replace__(completed_at=STAMP)
    assert refresh_stage(repos(w.state), LOOP, now=STAMP) == "in_progress"
    assert w.state.loops[LOOP].stage == "in_progress"
    assert w.state.loops[LOOP].updated_at == STAMP


def _approve_everything(state: BoardState) -> None:
    for slot in _documents().values():
        assert slot.current is not None
        state.documents.append(slot.current)
    reviewed = _all_reviewed()
    state.approvals.extend(
        [
            approval_row("a", LOOP, "analysis", revisions_json=reviewed),
            approval_row("r", LOOP, "roadmap", revisions_json=reviewed),
        ]
    )


def test_refreshing_an_unchanged_stage_writes_nothing() -> None:
    state = BoardState(loops={LOOP: loop_row(LOOP, stage="draft")})
    assert refresh_stage(repos(state), LOOP, now=STAMP) == "draft"
    assert state.loops[LOOP].updated_at == CREATED
    with pytest.raises(NotFound) as missing:
        refresh_stage(repos(state), "elsewhere", now=STAMP)
    assert missing.value.code == "loop_not_found"


# --- a document's state and the warnings ----------------------------------------------------------


def test_a_document_state_tells_empty_stale_approved_review_and_requested_changes() -> None:
    documents = _documents()
    assert document_state("info", document_slots(()), {}, {})["state"] == "empty"
    stale = {"analysis": ["analysis_ai_changed"]}
    assert document_state("analysis", documents, {}, stale)["state"] == "stale"
    assert document_state("analysis", documents, {}, stale)["stale_reasons"] == [
        "analysis_ai_changed"
    ]
    approved = document_slots([document_row("an-1", LOOP, "analysis", approved=True)])
    assert document_state("analysis", approved, {}, {})["state"] == "approved"
    newer = document_slots(
        [
            document_row("an-1", LOOP, "analysis", current=False, approved=True),
            document_row("an-2", LOOP, "analysis", revision=2),
        ]
    )
    assert document_state("analysis", newer, {}, {})["state"] == "draft"
    review = document_slots([document_row("an-1", LOOP, "analysis", status="ready_for_review")])
    assert document_state("analysis", review, {}, {})["state"] == "ready_for_review"
    old_flag = document_slots([document_row("an-1", LOOP, "analysis", status="approved")])
    assert document_state("analysis", old_flag, {}, {})["state"] == "draft"
    requested = latest_approvals(
        [
            approval_row(
                "c",
                LOOP,
                "analysis",
                decision="changes_requested",
                revisions_json=json.dumps({"analysis": "an-1"}),
            )
        ]
    )
    assert document_state("analysis", documents, requested, {})["state"] == "changes_requested"
    other = latest_approvals(
        [approval_row("c", LOOP, "roadmap", decision="changes_requested", revisions_json="{}")]
    )
    assert document_state("roadmap", documents, other, {})["state"] == "draft"


def test_a_document_state_carries_every_column_of_both_revisions() -> None:
    state = document_state("info", _documents(), {}, {})
    current = state["current"]
    assert current is not None
    assert list(current) == [
        "id",
        "loop_id",
        "kind",
        "revision_number",
        "content",
        "payload_json",
        "content_hash",
        "status",
        "source_info_revision_id",
        "source_analysis_ai_revision_id",
        "source_analysis_revision_id",
        "source_roadmap_ai_revision_id",
        "generation_run_id",
        "author_actor_id",
        "author_actor_type",
        "author_name",
        "provenance_json",
        "is_current",
        "is_approved",
        "created_at",
    ]
    assert state["approved"] is None


def test_warnings_name_stale_documents_the_stage_and_a_missing_analysis_approval() -> None:
    documents = _documents(ai="info-0")
    stale = stale_reasons(documents, {})
    codes = [warning["code"] for warning in loop_warnings("replanning", documents, {}, stale)]
    assert codes == [
        "document_stale",
        "document_stale",
        "document_stale",
        "document_stale",
        "plan_change_required",
        "approval_required",
    ]
    first = loop_warnings("draft", documents, {}, stale)[0]
    assert first == {
        "code": "document_stale",
        "kind": "analysis_ai",
        "reasons": ["info_changed"],
        "message": "Analysis Ai needs regeneration",
    }
    approvals = latest_approvals([approval_row("a", LOOP, "analysis")])
    quiet = loop_warnings("awaiting_qa", document_slots(()), approvals, {"info": ["x"]})
    assert [warning["code"] for warning in quiet] == ["qa_incomplete"]


def test_the_qa_summary_shows_the_open_cycle_or_else_the_latest() -> None:
    assert qa_summary([]) is None
    cycles = [
        qa_cycle_row("q1", LOOP, 1, status="rejected"),
        qa_cycle_row("q2", LOOP, 2, status="in_progress", card_id="card-1"),
        qa_cycle_row("q3", LOOP, 3, status="pending"),
    ]
    assert qa_summary(cycles) == {
        "cycle_id": "q2",
        "cycle_number": 2,
        "status": "in_progress",
        "card_id": "card-1",
        "open": True,
    }
    closed = [qa_cycle_row("q1", LOOP, 1, status="accepted"), qa_cycle_row("q0", LOOP, 0)]
    closed[1] = closed[1].__replace__(status="superseded")
    summary = qa_summary(closed)
    assert summary is not None
    assert summary["cycle_id"] == "q1"
    assert summary["open"] is False


# --- the shared rules -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("loop", "message"),
    [
        (loop_row(LOOP, completed_at=STAMP), "This Loop is completed and read-only"),
        (loop_row(LOOP, stage="completed"), "This Loop is completed and read-only"),
        (loop_row(LOOP, cancelled_at=STAMP), "This Loop was cancelled"),
        (loop_row(LOOP, stage="cancelled"), "This Loop was cancelled"),
        (loop_row(LOOP, archived_at=STAMP), "This Loop is archived"),
    ],
)
def test_completed_cancelled_and_archived_loops_are_read_only(loop: LoopsRow, message: str) -> None:
    with pytest.raises(Conflict) as refused:
        ensure_writable(loop)
    assert refused.value.code == "loop_read_only"
    assert refused.value.message == message
    assert refused.value.details == {"loop_id": LOOP}
    ensure_writable(loop_row(LOOP, stage="ready"))


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("draft", "approval_required"),
        ("planning", "approval_required"),
        ("analysis_review", "approval_required"),
        ("replanning", "plan_change_required"),
        ("roadmap_review", "plan_change_required"),
        ("ready", None),
        ("in_progress", None),
        ("awaiting_qa", None),
    ],
)
def test_delivery_runs_only_in_the_execution_stages(stage: str, code: str | None) -> None:
    loop = loop_row(LOOP, stage=stage)
    if code is None:
        ensure_execution_allowed(loop)
        return
    with pytest.raises(Conflict) as refused:
        ensure_execution_allowed(loop)
    assert refused.value.code == code
    assert refused.value.details == {"stage": stage, "loop_id": LOOP}


# --- reads ----------------------------------------------------------------------------------------


def _loops() -> list[LoopsRow]:
    return [
        loop_row("b-done", stage="completed", completed_at=STAMP).__replace__(sequence=1),
        loop_row("a-open", stage="draft").__replace__(sequence=3),
        loop_row("c-open", stage="planning").__replace__(sequence=2),
        loop_row("d-gone", stage="draft", archived_at=STAMP).__replace__(sequence=4),
    ]


def test_the_list_shows_open_loops_first_by_sequence_and_filters(settings: Settings) -> None:
    w = world(settings, *_loops())
    assert [entry["id"] for entry in w.service.list(BOARD_ID)] == ["c-open", "a-open"]
    everything = w.service.list(BOARD_ID, include_completed=True, include_archived=True)
    assert [entry["id"] for entry in everything] == ["c-open", "a-open", "d-gone", "b-done"]
    assert [entry["id"] for entry in w.service.list(BOARD_ID, stage="draft")] == ["a-open"]
    assert [entry["id"] for entry in w.service.list(BOARD_ID, stage="")] == ["c-open", "a-open"]
    assert w.service.list(BOARD_ID, stage="bogus") == []


def test_the_overview_shows_each_loop_as_its_own_read_does(settings: Settings) -> None:
    loops = _loops()
    w = world(settings, *loops)
    _approve_everything(w.state)
    w.state.documents.append(document_row("x", "c-open", "info"))
    w.state.plans = {"p": plan_row("p", LOOP), "q": plan_row("q", "c-open")}
    w.state.loops[LOOP] = loop_row(LOOP).__replace__(sequence=9)
    w.state.phases = {
        "ph": phase_row("ph", "c-open", "q", 1),
        "ph2": phase_row("ph2", "c-open", "q", 2),
    }
    w.state.plan_items = {"i1": plan_item_row("i1", "c-open", "q", "ph")}
    w.state.plan_items["i2"] = plan_item_row("i2", "c-open", "q", "ph")
    w.state.lists = {"l": list_row("l", "c-open", 1024)}
    w.state.cards = {
        "t1": card_row("t1", "l", "c-open", plan_item_id="i1").__replace__(
            kind="ticket", completed_at=STAMP
        ),
        "t2": card_row("t2", "l", "c-open", archived_at=STAMP).__replace__(kind="qa"),
        "m": card_row("m", "l", "c-open"),
    }
    w.state.qa_cycles = {"q1": qa_cycle_row("q1", "c-open", 1)}
    overview = w.service.list(BOARD_ID, include_completed=True, include_archived=True)
    assert overview == [w.service.get(BOARD_ID, entry["id"]) for entry in overview]
    planned = next(entry for entry in overview if entry["id"] == "c-open")
    assert planned["plan"] == {
        "plan_id": "q",
        "revision_number": 1,
        "activated_at": CREATED,
        "phase_count": 2,
        "ticket_total": 2,
        "ticket_completed": 1,
    }
    assert planned["progress"] == {
        "ticket_total": 2,
        "ticket_completed": 1,
        "ticket_archived_incomplete": 1,
    }
    assert planned["qa"] is not None
    first = next(entry for entry in overview if entry["id"] == LOOP)
    assert first["documents"]["roadmap"]["state"] == "draft"
    assert [warning["code"] for warning in first["warnings"]] == []


def test_an_entry_is_the_row_its_board_and_its_facts_in_the_former_key_order(
    settings: Settings,
) -> None:
    w = world(settings, loop_row(LOOP))
    entry = w.service.get(BOARD_ID, LOOP)
    assert list(entry)[-6:] == ["board_id", "documents", "plan", "qa", "progress", "warnings"]
    assert list(entry)[:3] == ["id", "name", "goal"]
    assert entry["board_id"] == BOARD_ID
    assert entry["plan"] is None
    assert entry["qa"] is None
    assert entry["progress"] == {
        "ticket_total": 0,
        "ticket_completed": 0,
        "ticket_archived_incomplete": 0,
    }
    assert entry["documents"]["info"]["state"] == "empty"
    assert [warning["code"] for warning in entry["warnings"]] == ["approval_required"]


def test_reads_check_the_board_and_the_loop(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP))
    with pytest.raises(NotFound) as missing:
        w.service.get(BOARD_ID, "elsewhere")
    assert missing.value.code == "loop_not_found"
    w.store.databases.clear()
    with pytest.raises(NotFound, match="Board database not found"):
        w.service.list(BOARD_ID)
    w.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound, match="Board not found"):
        w.service.list(BOARD_ID)
    assert w.store.commits == 0


def test_plan_and_readiness_come_from_the_plan_views_for_the_loop_row(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP, stage="ready"))
    assert w.service.plan(BOARD_ID, LOOP)["loop_id"] == LOOP
    assert w.service.readiness(BOARD_ID, LOOP)["stage"] == "ready"
    assert w.views.calls == [("plan_view", LOOP, "ready"), ("readiness", LOOP, "ready")]
    with pytest.raises(NotFound):
        w.service.readiness(BOARD_ID, "elsewhere")
    assert ("require_row", BOARD_ID) in w.checks.calls


# --- create ---------------------------------------------------------------------------------------


def test_a_new_loop_gets_its_key_its_columns_and_an_activity_entry(settings: Settings) -> None:
    w = world(settings, loop_row("old").__replace__(sequence=4, key="L-4"))
    w.state.loop_defaults = BoardLoopDefaultsRow(
        id=1, column_names_json=json.dumps(["Board", "Defaults"]), updated_at=CREATED
    )
    payload = LoopCreate(name="Email verification", goal="Verify", column_names=["A", "B"])
    entry, replayed = w.service.create(HUMAN, BOARD_ID, payload)
    assert replayed is False
    assert isinstance(entry, dict)
    loop = w.state.loops["new-1"]
    assert (loop.sequence, loop.key_prefix, loop.key, loop.stage, loop.version) == (
        5,
        "EM",
        "EM005",
        "draft",
        1,
    )
    assert (loop.created_by_actor_id, loop.created_by_name, loop.created_at) == (
        "actor-1",
        "Ada",
        STAMP,
    )
    columns = sorted(w.state.lists.values(), key=lambda row: row.position)
    assert [(row.id, row.name, row.position) for row in columns] == [
        ("new-2", "A", 1024),
        ("new-3", "B", 2048),
    ]
    assert [(row.id, row.action, row.entity_id) for row in w.state.activity] == [
        ("new-4", "loop.created", "new-1")
    ]
    assert json.loads(w.state.activity[0].changes_json) == {
        "name": "Email verification",
        "key": "EM005",
        "columns": ["A", "B"],
    }
    assert w.state.activity[0].request_id == "req-1"
    assert w.store.commits == 1


@pytest.mark.parametrize(
    ("stored", "columns"),
    [
        (json.dumps(["Todo", " ", "Done"]), ["Todo", "Done"]),
        (json.dumps({"Plan": 1, "Do": 2}), ["Plan", "Do"]),
        (json.dumps("ab"), ["a", "b"]),
        (json.dumps(None), None),
        ("not json", None),
        (json.dumps([]), None),
    ],
)
def test_a_new_loops_columns_come_from_the_request_then_the_board_then_the_settings(
    settings: Settings, stored: str, columns: list[str] | None
) -> None:
    w = world(settings)
    w.state.loop_defaults = BoardLoopDefaultsRow(id=1, column_names_json=stored, updated_at=CREATED)
    w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Loop"))
    names = [row.name for row in sorted(w.state.lists.values(), key=lambda row: row.position)]
    assert names == (columns if columns is not None else settings.list_names)


def test_stored_default_columns_that_are_a_number_fail_as_iterating_them_did(
    settings: Settings,
) -> None:
    w = world(settings)
    w.state.loop_defaults = BoardLoopDefaultsRow(id=1, column_names_json="7", updated_at=CREATED)
    with pytest.raises(TypeError):
        w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Loop"))
    assert w.state.loops == {}
    assert w.store.rollbacks == 1


def test_creation_needs_the_scope_and_an_active_board_before_anything_is_written(
    settings: Settings,
) -> None:
    w = world(settings)
    with pytest.raises(Forbidden):
        w.service.create(READER, BOARD_ID, LoopCreate(name="Loop"))
    w.checks.archived = frozenset({BOARD_ID})
    with pytest.raises(Conflict) as archived:
        w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Loop"))
    assert archived.value.code == "board_archived"
    assert w.state.loops == {}
    assert w.store.commits == 0


def test_a_replayed_key_answers_the_stored_loop_and_another_payload_is_refused(
    settings: Settings,
) -> None:
    w = world(settings)
    first, replayed = w.service.create(
        HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k"
    )
    assert replayed is False
    record = w.state.idempotency[("actor-1", "k")]
    assert record.created_at == STAMP
    assert record.expires_at == "2026-11-04T10:00:00Z"
    again, replayed = w.service.create(
        HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k"
    )
    assert replayed is True
    assert again == json.loads(json.dumps(first))
    assert len(w.state.loops) == 1
    with pytest.raises(Conflict) as reused:
        w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Twice"), idempotency_key="k")
    assert reused.value.code == "idempotency_key_reused"
    other_actor = ActorContext(
        actor_id="actor-9", actor_type="user", actor_name="Eve", scopes=SCOPES
    )
    w.service.create(other_actor, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k")
    assert len(w.state.loops) == 2


def test_an_expired_key_runs_the_request_again_and_replaces_the_record(settings: Settings) -> None:
    w = world(settings)
    w.state.idempotency[("actor-1", "k")] = IdempotencyRecordsRow(
        actor_id="actor-1",
        idempotency_key="k",
        request_hash="stale",
        response_json="{}",
        created_at=CREATED,
        expires_at=CREATED,
    )
    with pytest.raises(Conflict):
        w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k")
    w.state.idempotency.clear()
    w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k")
    w.clock.now = NOW + timedelta(days=1, seconds=1)
    _, replayed = w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k")
    assert replayed is False
    assert len(w.state.loops) == 2
    assert w.state.idempotency[("actor-1", "k")].created_at == "2026-11-04T10:00:01Z"
    w.clock.now = NOW + timedelta(days=2, seconds=1)
    _, replayed = w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Once"), idempotency_key="k")
    assert replayed is True


# --- update, cancel, archive ----------------------------------------------------------------------


def test_an_update_bumps_the_version_logs_the_change_and_refreshes_the_stage(
    settings: Settings,
) -> None:
    w = world(settings, loop_row(LOOP, stage="planning"))
    entry = w.service.update(HUMAN, BOARD_ID, LOOP, LoopUpdate(version=1, name="New", goal="G"))
    loop = w.state.loops[LOOP]
    assert (loop.name, loop.goal, loop.version, loop.updated_at) == ("New", "G", 2, STAMP)
    assert loop.stage == "draft"
    assert entry["stage"] == "draft"
    assert [row.action for row in w.state.activity] == ["loop.updated"]
    assert json.loads(w.state.activity[0].changes_json) == {
        "name": {"before": "Loop loop-a", "after": "New"},
        "goal": {"changed": True},
    }


def test_an_update_that_changes_nothing_writes_nothing(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP, stage="planning"))
    entry = w.service.update(
        HUMAN, BOARD_ID, LOOP, LoopUpdate(version=1, name="Loop loop-a", goal="")
    )
    assert entry["version"] == 1
    assert w.state.loops[LOOP].stage == "planning"
    assert w.state.activity == []


def test_an_update_checks_the_version_and_a_read_only_loop(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP), loop_row("done", completed_at=STAMP))
    with pytest.raises(VersionConflict) as stale:
        w.service.update(HUMAN, BOARD_ID, LOOP, LoopUpdate(version=2, name="x"))
    assert stale.value.details == {"expected_version": 2, "current_version": 1}
    with pytest.raises(Conflict) as done:
        w.service.update(HUMAN, BOARD_ID, "done", LoopUpdate(version=1, name="x"))
    assert done.value.code == "loop_read_only"
    with pytest.raises(Forbidden):
        w.service.update(READER, BOARD_ID, LOOP, LoopUpdate(version=1, name="x"))
    assert w.store.commits == 0


def test_only_a_person_cancels_a_loop_and_only_once(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP))
    with pytest.raises(Forbidden) as agent:
        w.service.cancel(AGENT, BOARD_ID, LOOP, LoopCancel(version=1))
    assert agent.value.code == "human_action_required"
    with pytest.raises(VersionConflict):
        w.service.cancel(HUMAN, BOARD_ID, LOOP, LoopCancel(version=3))
    entry = w.service.cancel(HUMAN, BOARD_ID, LOOP, LoopCancel(version=1, reason="Not needed"))
    assert (entry["stage"], entry["cancelled_at"], entry["version"]) == ("cancelled", STAMP, 2)
    assert json.loads(w.state.activity[0].changes_json) == {"reason": "Not needed"}
    with pytest.raises(Conflict) as again:
        w.service.cancel(HUMAN, BOARD_ID, LOOP, LoopCancel(version=2))
    assert again.value.message == "This Loop was cancelled"


def test_archiving_is_idempotent_and_allowed_for_a_finished_loop(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP, completed_at=STAMP, stage="completed"))
    entry = w.service.archive(HUMAN, BOARD_ID, LOOP)
    assert (entry["archived_at"], entry["version"]) == (STAMP, 2)
    w.service.archive(HUMAN, BOARD_ID, LOOP)
    assert w.state.loops[LOOP].version == 2
    assert [row.action for row in w.state.activity] == ["loop.archived"]
    with pytest.raises(Forbidden):
        w.service.archive(READER, BOARD_ID, LOOP)


# --- a human confirms a human-only Ticket ---------------------------------------------------------


def _human_ticket(settings: Settings, *, stage: str = "ready") -> World:
    w = world(settings, loop_row(LOOP, stage=stage).__replace__(current_plan_id="p"))
    _approve_everything(w.state)
    w.state.plans = {"p": plan_row("p", LOOP)}
    w.state.lists = {"l": list_row("l", LOOP, 1024), "x": list_row("x", "other", 1024)}
    w.state.loops["other"] = loop_row("other").__replace__(sequence=2, key="L-2")
    w.state.cards = {
        "h": card_row("h", "l", LOOP).__replace__(required_actor="human", kind="ticket"),
        "a": card_row("a", "l", LOOP).__replace__(kind="ticket"),
        "o": card_row("o", "x", "other").__replace__(required_actor="human"),
    }
    return w


def test_a_person_confirms_a_human_ticket_and_the_stage_moves_on(settings: Settings) -> None:
    w = _human_ticket(settings)
    w.views.items = [readiness_item("h", human=True)]
    card = w.service.confirm_human_ticket(
        HUMAN, BOARD_ID, LOOP, "h", HumanConfirmation(version=1, note="Done")
    )
    row = w.state.cards["h"]
    assert (row.completed_at, row.human_confirmed_at, row.human_confirmed_by_actor_id) == (
        STAMP,
        STAMP,
        "actor-1",
    )
    assert row.version == 2
    assert card["id"] == "h"
    assert card["version"] == 2
    assert w.state.loops[LOOP].stage == "in_progress"
    assert [(entry.action, entry.entity_id) for entry in w.state.activity] == [
        ("card.human_confirmed", "h")
    ]
    assert json.loads(w.state.activity[0].changes_json) == {"note": "Done", "ticket_key": None}


def test_a_confirmation_is_refused_to_an_agent_and_for_the_wrong_ticket(settings: Settings) -> None:
    w = _human_ticket(settings)
    confirm = HumanConfirmation(version=1)
    with pytest.raises(Forbidden) as agent:
        w.service.confirm_human_ticket(AGENT, BOARD_ID, LOOP, "h", confirm)
    assert agent.value.code == "human_action_required"
    with pytest.raises(NotFound, match="Ticket not found"):
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "o", confirm)
    with pytest.raises(NotFound, match="Ticket not found"):
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "missing", confirm)
    with pytest.raises(VersionConflict) as stale:
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "h", HumanConfirmation(version=4))
    assert stale.value.message == "Ticket was modified by another actor"
    with pytest.raises(ValidationFailure) as not_human:
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "a", confirm)
    assert not_human.value.details == {"ticket_id": "a"}
    assert w.state.cards["h"].completed_at is None


def test_a_confirmation_needs_an_executing_unblocked_writable_loop(settings: Settings) -> None:
    w = _human_ticket(settings, stage="replanning")
    confirm = HumanConfirmation(version=1)
    with pytest.raises(Conflict) as frozen:
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "h", confirm)
    assert frozen.value.code == "plan_change_required"
    w = _human_ticket(settings)
    w.views.items = [readiness_item("h", ready=False, blockers=(BLOCKER,))]
    with pytest.raises(Conflict) as blocked:
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "h", confirm)
    assert blocked.value.code == "ticket_blocked"
    assert blocked.value.details == {"blockers": [BLOCKER]}
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(archived_at=STAMP)
    with pytest.raises(Conflict) as archived:
        w.service.confirm_human_ticket(HUMAN, BOARD_ID, LOOP, "h", confirm)
    assert archived.value.code == "loop_read_only"
    assert w.state.cards["h"].completed_at is None
    assert w.state.activity == []


@pytest.mark.parametrize("stored", ["null", "[1, 2]", '"text"'])
def test_a_stored_answer_that_is_not_an_object_counts_as_none(
    settings: Settings, stored: str
) -> None:
    w = world(settings)
    # A record with the same fingerprint, as the first request stored it, under key "k".
    w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Probe"), idempotency_key="p")
    record = w.state.idempotency[("actor-1", "p")]
    w.state.idempotency[("actor-1", "k")] = record.__replace__(
        idempotency_key="k", response_json=stored
    )
    _, replayed = w.service.create(HUMAN, BOARD_ID, LoopCreate(name="Probe"), idempotency_key="k")
    assert replayed is False
    assert len(w.state.loops) == 2
    assert w.state.idempotency[("actor-1", "k")].response_json.startswith("{")
