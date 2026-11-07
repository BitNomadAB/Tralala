"""``write_analysis`` and ``write_roadmap`` on the fakes: the real LoopDocumentService and plan
service on an in-memory board, handed to the tools as the one attribute ``PlanWriting`` declares;
the id mapping as a pure function; then what ``tools/list`` and ``/llms.txt`` say about the tools.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, ValidationFailure, VersionConflict
from app.schemas.loops import CRITERION_MAX_CHARS, ApprovalRequest, InfoRevisionWrite, PlanPayload
from app.services.agent_tools import (
    ToolResult,
    map_plan_ids,
    tool_catalog,
    write_analysis,
    write_roadmap,
)
from app.services.loop_documents import LoopDocumentService
from app.services.loop_plans import LoopPlanService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    list_row,
    loop_row,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
LOOP = "6d1f2a3b-4c5d-4e6f-8a7b-9c0d1e2f3a4b"
SCOPES = frozenset({"loops:read", "loops:write", "loops:generate", "loops:review"})
HUMAN = ActorContext(actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES)
WORKER = ActorContext(actor_id="agent-1", actor_type="agent", actor_name="Coder", scopes=SCOPES)
NAMESPACE = uuid.UUID(LOOP)
P1, P2 = (str(uuid.uuid5(NAMESPACE, f"phase:{name}")) for name in ("p1", "p2"))
T1, T2 = (str(uuid.uuid5(NAMESPACE, f"ticket:{name}")) for name in ("t1", "t2"))
KEPT = "00000000-0000-4000-8000-000000000011"


def finding(finding_id: str, category: str, plain_language: str) -> dict[str, JsonValue]:
    return {
        "id": finding_id,
        "title": f"Finding {finding_id}",
        "category": category,
        "technical_detail": f"What an engineer reads about {finding_id}.",
        "plain_language": plain_language,
    }


def analysis_payload(*findings: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "outcome": "Verify addresses",
        "findings": [*findings],
        "recommendation": "Extend the sign-in.",
    }


ANALYSIS = analysis_payload(
    finding("F-1", "reuse", "The sign-in we have can send the e-mail."),
    finding("F-2", "risk", "Some people may never get the e-mail."),
)


def phase(
    phase_id: str, number: int, *tickets: dict[str, JsonValue], after: str = ""
) -> dict[str, JsonValue]:
    return {
        "id": phase_id,
        "number": number,
        "name": f"Phase {number}",
        "prerequisite_phase_ids": [after] if after else [],
        "tickets": [*tickets],
    }


def ticket(
    ticket_id: str, *, after_ticket: str = "", after_phase: str = ""
) -> dict[str, JsonValue]:
    return {
        "id": ticket_id,
        "title": f"Ticket {ticket_id}",
        "acceptance_criteria": ["it works"],
        "prerequisite_ticket_ids": [after_ticket] if after_ticket else [],
        "prerequisite_phase_ids": [after_phase] if after_phase else [],
    }


def plan_payload(*phases: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {"summary": "Two phases", "phases": [*phases]}


PLAN = plan_payload(
    phase("p1", 1, ticket("t1")),
    phase("p2", 2, ticket("t2", after_ticket="t1"), ticket(KEPT, after_phase="p1"), after="p1"),
)


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(frozen=True, slots=True)
class World:
    """What the tools declare they use of the composition root, and the board under it."""

    loop_document: LoopDocumentService
    state: BoardState

    @property
    def repos(self) -> FakeBoardRepositories:
        return FakeBoardRepositories(self.state)

    def current(self, kind: str) -> str:
        row = self.repos.documents.current(LOOP, kind)
        assert row is not None
        return row.id

    def info(self, content: str = "Users must confirm their address.") -> None:
        self.loop_document.save_info(HUMAN, BOARD_ID, LOOP, InfoRevisionWrite(content=content))

    def review(self, scope: str, decision: str = "approved") -> None:
        version = self.state.loops[LOOP].version
        request = ApprovalRequest.model_validate({"decision": decision, "version": version})
        self.loop_document.review(HUMAN, BOARD_ID, LOOP, scope, request)


def world(*, approved_analysis: bool = False) -> World:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="draft")}
    state.lists = {"todo": list_row("todo", LOOP, 1024)}
    ids = Ids()
    plans = LoopPlanService(clock=lambda: NOW, new_id=ids)
    service = LoopDocumentService(
        FakeBoardChecks(), FakeBoardUnitOfWork(state), plans, clock=lambda: NOW, new_id=ids
    )
    w = World(service, state)
    w.info()
    if approved_analysis:
        write(w, "analysis", ANALYSIS)
        w.review("analysis")
    return w


def write(w: World, argument: str, payload: JsonValue, **extra: str) -> ToolResult:
    """``write_analysis`` for an ``analysis``, ``write_roadmap`` for a ``plan``, as the worker."""
    args: dict[str, JsonValue] = {"board_id": BOARD_ID, "loop_id": LOOP, argument: payload}
    args.update(extra)
    handler = write_analysis if argument == "analysis" else write_roadmap
    return handler(w, WORKER, args)


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def field(value: object, *path: str) -> object:
    for key in path:
        assert _is_mapping(value)
        value = value[key]
    return value


def keys(value: object) -> list[str]:
    assert _is_mapping(value)
    return list(value)


# --- write_analysis ------------------------------------------------------------------------------


def test_write_analysis_stores_both_views_from_mcp_and_names_the_next_step() -> None:
    w = world()
    answer = write(w, "analysis", ANALYSIS)
    technical = w.repos.documents.current(LOOP, "analysis_ai")
    human = w.repos.documents.current(LOOP, "analysis")
    assert technical is not None
    assert human is not None
    assert json.loads(technical.payload_json or "{}")["findings"][1]["id"] == "F-2"
    provenance = {"submitted": True, "through": "mcp", "author": "Coder", "actor_id": "agent-1"}
    assert json.loads(technical.provenance_json) == provenance
    assert json.loads(human.provenance_json) == {**provenance, "rendered": True}
    assert "Some people may never get the e-mail." in human.content
    assert field(answer, "documents", "analysis_ai") == {
        "state": "ready_for_review",
        "revision_id": technical.id,
        "revision_number": 1,
    }
    assert field(answer, "documents", "analysis", "revision_id") == human.id
    assert answer["stale_reasons"] == {}
    # Without a board agent to write it for people, the answer says why the view stays rendered.
    assert answer["human_view"] == {"status": "skipped", "run_id": None, "reason": "not configured"}
    assert "Analysis tab" in str(answer["next_step"])
    assert w.state.loops[LOOP].stage == "analysis_review"


def test_write_analysis_accepts_the_object_written_as_a_json_string() -> None:
    w = world()
    write(w, "analysis", json.dumps(ANALYSIS))
    assert w.repos.documents.current(LOOP, "analysis_ai") is not None


def test_a_material_finding_without_plain_language_is_refused_by_its_id() -> None:
    w = world()
    risky = analysis_payload(finding("F-1", "reuse", "Fine."), finding("F-3", "legal", " "))
    with pytest.raises(ValidationFailure) as refused:
        write(w, "analysis", risky)
    assert refused.value.details == {"finding_ids": ["F-3"]}
    assert w.repos.documents.current(LOOP, "analysis_ai") is None


def test_a_payload_that_breaks_the_schema_answers_one_line_per_error() -> None:
    w = world()
    broken: dict[str, JsonValue] = {
        "findings": [{"id": "F-1", "title": "x", "category": "rumour", "technical_detail": "y"}],
        "colour": "blue",
    }
    with pytest.raises(ValidationFailure) as refused:
        write(w, "analysis", broken)
    details = refused.value.details
    assert details is not None
    assert (details["argument"], details["error_count"]) == ("analysis", 4)
    errors = details["errors"]
    assert _is_list(errors)
    assert sorted(str(line).split(":", 1)[0] for line in errors) == [
        "analysis.colour",
        "analysis.findings.0.category",
        "analysis.findings.0.plain_language",
        "analysis.outcome",
    ]
    assert "analysis.outcome: Field required" in refused.value.message
    with pytest.raises(ValidationFailure, match="analysis is required"):
        write_analysis(w, WORKER, {"board_id": BOARD_ID, "loop_id": LOOP})
    with pytest.raises(ValidationFailure, match="Invalid JSON"):
        write(w, "analysis", "{not json")


def test_write_analysis_from_an_info_that_changed_is_stale() -> None:
    w = world()
    first = w.current("info")
    w.info("Users must confirm by e-mail.")
    with pytest.raises(VersionConflict) as stale:
        write(w, "analysis", ANALYSIS, expected_info_revision_id=first)
    assert stale.value.code == "document_stale"
    assert field(stale.value.details, "current_revision_id") == w.current("info")
    write(w, "analysis", ANALYSIS, expected_info_revision_id=w.current("info"))


def test_write_analysis_never_replaces_an_approved_analysis() -> None:
    w = world(approved_analysis=True)
    with pytest.raises(Forbidden) as refused:
        write(w, "analysis", ANALYSIS)
    assert refused.value.code == "human_action_required"
    w.review("analysis", decision="changes_requested")
    write(w, "analysis", ANALYSIS)


# --- write_roadmap -------------------------------------------------------------------------------


def test_write_roadmap_needs_an_approved_analysis() -> None:
    w = world()
    write(w, "analysis", ANALYSIS)
    with pytest.raises(Conflict) as refused:
        write(w, "plan", PLAN)
    assert refused.value.code == "approval_required"
    assert refused.value.details == {"scope": "analysis"}
    assert w.state.plans == {}


def test_write_roadmap_turns_short_ids_into_stable_uuids_and_keeps_them() -> None:
    w = world(approved_analysis=True)
    answer = write(w, "plan", PLAN)
    assert answer["id_map"] == {"phases": {"p1": P1, "p2": P2}, "tickets": {"t1": T1, "t2": T2}}
    (plan,) = w.state.plans.values()
    assert field(answer, "plan") == {"plan_id": plan.id, "phases": 2, "tickets": 3}
    assert sorted(w.state.phases) == sorted([P1, P2])
    assert {item.id for item in w.state.plan_items.values()} == {T1, T2, KEPT}
    second = json.loads(plan.payload_json)["phases"][1]
    assert second["prerequisite_phase_ids"] == [P1]
    assert [entry["prerequisite_ticket_ids"] for entry in second["tickets"]] == [[T1], []]
    assert [entry["prerequisite_phase_ids"] for entry in second["tickets"]] == [[], [P1]]
    assert field(answer, "documents", "roadmap_ai", "state") == "ready_for_review"
    assert "RoadMap tab" in str(answer["next_step"])
    # The same ids again: the same Phases and Tickets, and their keys stay.
    planned = {item.id: item.key for item in w.state.plan_items.values()}
    again = write(w, "plan", PLAN)
    assert again["id_map"] == answer["id_map"]
    assert len(w.state.plans) == 2
    assert {item.id: item.key for item in w.state.plan_items.values()} == planned


def test_a_reference_to_an_unknown_id_is_answered_with_the_id_the_model_wrote() -> None:
    w = world(approved_analysis=True)
    broken = plan_payload(phase("p1", 1, ticket("t1")), phase("p3", 3, ticket("t3"), after="p9"))
    with pytest.raises(ValidationFailure) as refused:
        write(w, "plan", broken)
    assert (refused.value.code, refused.value.details) == (
        "invalid_dependency_graph",
        {"phase_id": "p3", "missing": "p9"},
    )


def test_write_roadmap_from_an_analysis_that_changed_is_stale() -> None:
    w = world(approved_analysis=True)
    with pytest.raises(VersionConflict) as stale:
        write(w, "plan", PLAN, expected_analysis_revision_id="an-older-one")
    assert field(stale.value.details, "kind") == "analysis_ai"
    write(w, "plan", PLAN, expected_analysis_revision_id=w.current("analysis_ai"))


def test_ids_that_are_uuids_pass_and_short_ones_map_the_same_way_every_time() -> None:
    plan = PlanPayload.model_validate(PLAN)
    first, ids = map_plan_ids(plan, LOOP)
    assert map_plan_ids(plan, LOOP) == (first, ids)
    assert [entry.id for entry in first.phases] == [P1, P2]
    assert [entry.id for entry in first.phases[1].tickets] == [T2, KEPT]
    assert ids["tickets"] == {"t1": T1, "t2": T2}
    other, _ = map_plan_ids(plan, "00000000-0000-4000-8000-0000000000ff")
    assert other.phases[0].id != P1
    # A loop id that is not a UUID still maps deterministically; the service finds no such Loop.
    assert map_plan_ids(plan, "loop-a") == map_plan_ids(plan, "loop-a")


# --- the catalogue, tools/list and /llms.txt -----------------------------------------------------


def test_an_acceptance_criterion_holds_a_thousand_characters_and_no_more() -> None:
    # A criterion of a real plan names the fields, filters and refusals it covers (PLN-019: two
    # of the agent-workspace plan's criteria are 516 and 531 characters long).
    w = world(approved_analysis=True)
    longest = "c" * CRITERION_MAX_CHARS
    planned = ticket("t1")
    planned["acceptance_criteria"] = [longest]
    write(w, "plan", plan_payload(phase("p1", 1, planned)))
    (item,) = w.state.plan_items.values()
    assert json.loads(item.acceptance_criteria_json) == [longest]
    planned["acceptance_criteria"] = [longest + "c"]
    with pytest.raises(ValidationFailure) as refused:
        write(w, "plan", plan_payload(phase("p1", 1, planned)))
    assert "plan.phases.0.tickets.0.acceptance_criteria.0: String should have at most 1000" in (
        refused.value.message
    )
    # The evidence a Ticket expects stays a list of short items.
    planned["acceptance_criteria"] = ["it works"]
    planned["expected_evidence"] = ["e" * 501]
    with pytest.raises(ValidationFailure) as short:
        write(w, "plan", plan_payload(phase("p1", 1, planned)))
    assert "expected_evidence.0: String should have at most 500" in short.value.message


def test_tools_list_carries_the_payload_schemas_with_their_definitions() -> None:
    token = ActorContext(
        actor_id="agent-2",
        actor_type="agent",
        actor_name="w",
        scopes=frozenset({"loops:generate"}),
    )
    listed = {str(tool["name"]): tool["inputSchema"] for tool in tool_list(token)}
    assert {"write_analysis", "write_roadmap"} <= set(listed)
    analysis = listed["write_analysis"]
    assert field(analysis, "properties", "analysis", "type") == "object"
    findings = field(analysis, "properties", "analysis", "properties", "findings", "items")
    assert findings == {"$ref": "#/$defs/AnalysisFinding"}
    assert "plain_language" in keys(field(analysis, "$defs", "AnalysisFinding", "properties"))
    assert field(analysis, "required") == ["board_id", "loop_id", "analysis"]
    plan = listed["write_roadmap"]
    assert sorted(keys(field(plan, "$defs"))) == ["PlanPhase", "PlanTicket"]
    assert keys(field(plan, "properties", "plan", "properties")) == [
        "schema_version",
        "summary",
        "phases",
    ]
    assert tool_catalog()["write_roadmap"].handler is write_roadmap


def test_the_bootstrap_points_an_object_argument_at_the_loop_context(settings: Settings) -> None:
    bootstrap = render_bootstrap(settings)
    for tool, argument in (("write_analysis", "analysis"), ("write_roadmap", "plan")):
        section = bootstrap.split(f"### {tool} (", 1)[1].split("\n### ", 1)[0]
        (line,) = [entry for entry in section.splitlines() if entry.startswith(f"- `{argument}`")]
        assert line.startswith(f"- `{argument}` (required): The ")
        assert "`GET /api/v1/boards/{board_id}/loops/{loop_id}/context`" in line
        assert "PlanPhase" not in section
        assert "AnalysisFinding" not in section
    rules = bootstrap.split("## 4. ", 1)[1].split("\n## 5. ", 1)[0]
    assert "You never replace an" in rules
