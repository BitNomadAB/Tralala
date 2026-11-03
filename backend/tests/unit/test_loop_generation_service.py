"""LoopGenerationService on the in-memory fakes, with the provider call scripted and every run
executed inline: which agent a run gets, what a run needs before it starts, how a run captures its
input, repairs, promotes or refuses the model's output, how a key replays a start, and how runs are
cancelled, retried, recovered and read. A repository snapshot reaches the model and the run's own
record; the API answer names the repository and its commit, never its file paths. A failed run
keeps the real error without a prompt or a credential, and every run logs its start and its end."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailure
from app.db.generated.board import LoopDocumentsRow, LoopGenerationRunsRow, LoopsRow
from app.db.generated.registry import BoardsRow
from app.repositories.board import BoardRepositories
from app.schemas.loops import (
    AnalysisPayload,
    CandidateSubmission,
    GenerationRequest,
    PlanPayload,
    QaInstructions,
)
from app.services.agents import EffectiveRole
from app.services.idempotency import request_fingerprint
from app.services.loop_documents import LoopDocumentService
from app.services.loop_documents_human import compose_human_view
from app.services.loop_documents_render import render_traceability
from app.services.loop_documents_views import DocumentsView
from app.services.loop_generation import MAX_REPAIRS, PURPOSE_PROMPTS, LoopGenerationService
from app.services.loop_generation_prompts import DEFAULT_CONTEXT_CHARS
from app.services.loop_generation_report import MAX_EXCEPTION_TEXT
from app.services.loop_generation_runs import MAX_OUTPUT_CHARS, stored_output
from app.services.loop_generation_trace import parse_steps
from app.services.loop_links import LoopWorkflowLinks
from app.services.loop_plans import LoopPlanService
from app.services.repo_snapshot import FetchedRepository
from app.services.runtime import Completion, ResponseSchema
from app.services.runtime_tools import Message, ToolChoice, ToolDefinition
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    approval_row,
    document_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import (
    RegistryState,
    agent_row,
    board_agent_row,
    board_row,
    registry_unit_of_work,
    role_template_row,
)
from tests.unit.log_lines import events

MOMENT = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
OTHER = "loop-b"
SETTINGS = object()
ADA = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=frozenset({"loops:generate"})
)

AGENTS = {
    "alpha": agent_row("alpha", name="Alpha", model="m-1"),
    "beta": agent_row("beta", name="Beta", model="m-b"),
    "off": agent_row("off", name="Off", enabled=False),
    "org": agent_row("org", name="Org", role_template_id="role-org"),
    "legacy": agent_row("legacy", name="Legacy", connection_type="webhook"),
}

ANALYSIS: dict[str, JsonValue] = {
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
PAYLOAD = AnalysisPayload.model_validate(ANALYSIS).model_dump()
QA: dict[str, JsonValue] = {
    "summary": "Check the export",
    "scenarios": [
        {
            "id": "S1",
            "title": "Export works",
            "kind": "happy_path",
            "steps_ai": ["Call the export"],
            "steps_human": ["Click Export"],
            "expected_result": "A file is written",
        }
    ],
}
# What a run captured from a Loop that holds only its Info revision.
SOURCES = {
    "info": "info-1",
    "analysis_ai": None,
    "analysis": None,
    "roadmap_ai": None,
    "roadmap": None,
}
REPOSITORIES: list[dict[str, JsonValue]] = [
    {
        "id": "repo-1",
        "name": "acme app",
        "branch": "main",
        "commit_sha": "abc123",
        "file_count": 1,
        "truncated": True,
        "files": [{"path": "src/app.py", "content": "print('hello')"}],
    },
    {"id": "repo-2", "name": "docs", "error": "unreachable"},
]
PHASE = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PHASE = "99999999-9999-4999-8999-999999999999"


def roadmap(prerequisites: Sequence[str] = ()) -> dict[str, JsonValue]:
    """A RoadMap of one Phase with one Ticket; the Phase waits for ``prerequisites``."""
    return {
        "summary": "One phase",
        "phases": [
            {
                "id": PHASE,
                "number": 1,
                "name": "Database",
                "prerequisite_phase_ids": list(prerequisites),
                "tickets": [
                    {
                        "id": "22222222-2222-4222-8222-222222222222",
                        "title": "Add columns",
                        "acceptance_criteria": ["ok"],
                    }
                ],
            }
        ],
    }


USAGE: dict[str, JsonValue] = {"prompt_tokens": 1200, "completion_tokens": 300}
# What every result of the first run records about where it came from.
PROVENANCE = {
    "generation_run_id": "id-1",
    "agent_id": "alpha",
    "agent_name": "Alpha",
    "model": "m-2",
}
# The columns a run's answer carries: no captured input, role or creator, and parsed JSON.
RUN_KEYS = {
    "id",
    "trace",
    "loop_id",
    "purpose",
    "status",
    "input_hash",
    "error_code",
    "error_message",
    "attempts",
    "agent_id",
    "agent_name",
    "model",
    "created_at",
    "started_at",
    "finished_at",
    "phase",
    "output",
    "source_revisions",
    "usage",
}

type Answer = Completion


def answer(text: str, *, usage: JsonValue = None) -> Answer:
    return {
        "ok": True,
        "error": None,
        "text": text,
        "tool_calls": [],
        "usage": usage or {"total_tokens": 42},
        "model": "m-2",
    }


VALID = answer(json.dumps(ANALYSIS))
FAILED: Answer = {"ok": False, "error": "boom", "text": "", "tool_calls": []}


# --- the collaborators ---------------------------------------------------------------------------


@dataclass(slots=True)
class Call:
    settings: object
    agent_id: object
    system_prompt: str
    messages: list[Message]
    running: dict[str, str | None]
    """The phase of every running run when the provider was called."""
    response_schema: ResponseSchema | None = None


@dataclass
class Provider:
    """The provider call, scripted: one answer per call, in order. ``before`` runs once, ahead of
    the first answer, as another request could while the model works; ``raises`` breaks the call."""

    state: BoardState
    answers: list[Answer]
    calls: list[Call] = field(default_factory=list[Call])
    before: Callable[[], None] | None = None
    raises: Exception | None = None

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: Sequence[Message],
        response_schema: ResponseSchema | None,
        tools: Sequence[ToolDefinition] | None = None,
        tool_choice: ToolChoice = "auto",
    ) -> Answer:
        del tools, tool_choice  # these agents do not take tools
        runs = self.state.generation_runs.values()
        running = {row.id: row.phase for row in runs if row.status == "running"}
        self.calls.append(
            Call(
                settings,
                agent_row["id"],
                system_prompt,
                list(messages),
                running,
                response_schema,
            )
        )
        hook, self.before = self.before, None
        if hook is not None:
            hook()
        if self.raises is not None:
            raise self.raises
        return self.answers.pop(0)

    def context(self, index: int = 0) -> dict[str, JsonValue]:
        """The context JSON the model was sent in one call."""
        message = self.calls[index].messages[0]["content"]
        loaded: dict[str, JsonValue] = json.loads(message.split("Context (JSON):\n", 1)[1])
        return loaded


class Boards:
    """BoardService as generation reads it: the board takes writes, and it has a name."""

    def ensure_active(self, board_id: str) -> object:
        return board_id

    def require_row(self, board_id: str) -> BoardsRow:
        return board_row(board_id, name="Delivery")


class Roles:
    def effective_role(self, agent_id: str) -> EffectiveRole:
        prompt = f"You are {agent_id}."
        return {
            "agent_id": agent_id,
            "agent_name": agent_id.title(),
            "role_template_id": "role-analyst",
            "role_template_name": "Analyst",
            "role_template_updated_at": None,
            "template_system_prompt": prompt,
            "override_system_prompt": None,
            "system_prompt": prompt,
            "role_source": "template",
        }


@dataclass
class Preferences:
    """The Loop's stored agent per purpose."""

    stored: dict[str, str]

    def resolve(self, board_id: str, loop_id: str, purpose: str) -> str | None:
        del board_id, loop_id
        return self.stored.get(purpose)


@dataclass
class Snapshots:
    """The board's repositories; records the phase the run was in when they were fetched and the
    budget it handed over."""

    state: BoardState
    entries: list[dict[str, JsonValue]]
    phases: list[str | None] = field(default_factory=list[str | None])
    budgets: list[int] = field(default_factory=list[int])

    def for_board(self, board_id: str, *, budget_chars: int) -> Sequence[Mapping[str, JsonValue]]:
        del board_id
        self.phases += [
            row.phase for row in self.state.generation_runs.values() if row.status == "running"
        ]
        self.budgets.append(budget_chars)
        return self.entries

    def fetch(self, board_id: str) -> Sequence[FetchedRepository]:
        del board_id
        return [FetchedRepository(dict(entry), None) for entry in self.entries]

    def snapshot_of(
        self, fetched: Sequence[FetchedRepository], *, budget_chars: int
    ) -> Sequence[Mapping[str, JsonValue]]:
        self.budgets.append(budget_chars)
        return [item.entry for item in fetched]


@dataclass
class QaRecorder:
    """``LoopQaService.apply_instructions``, recorded: (Loop, instructions, run, provenance)."""

    applied: list[tuple[str, QaInstructions, str, dict[str, object]]] = field(
        default_factory=list[tuple[str, QaInstructions, str, dict[str, object]]]
    )

    def __call__(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        instructions: QaInstructions,
        /,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> object:
        del repos
        self.applied.append((loop.id, instructions, run_id, dict(provenance)))
        return {"cycle_id": "cycle-1"}


class Ids:
    """id-1, id-2, ... in call order, shared by the generation, document and plan services."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"id-{self.issued}"


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    provider: Provider
    snapshots: Snapshots
    qa: QaRecorder
    service: LoopGenerationService

    def run(self, run_id: str = "id-1") -> LoopGenerationRunsRow:
        return self.state.generation_runs[run_id]

    def kinds(self) -> list[str]:
        return [row.kind for row in self.state.documents]


def run_row(
    run_id: str,
    *,
    status: str = "queued",
    purpose: str = "analysis",
    loop_id: str = LOOP,
    agent_id: str = "alpha",
    created_at: str = STAMP,
) -> LoopGenerationRunsRow:
    return LoopGenerationRunsRow(
        id=run_id,
        loop_id=loop_id,
        purpose=purpose,
        status=status,
        input_json="{}",
        input_hash="",
        source_revisions_json="{}",
        output_json="{}",
        error_code=None,
        error_message=None,
        attempts=0,
        agent_id=agent_id,
        agent_name=AGENTS[agent_id].name,
        model=None,
        role_snapshot_json="{}",
        usage_json="{}",
        created_by_actor_id="actor-1",
        created_by_actor_type="user",
        created_at=created_at,
        started_at=None,
        finished_at=None,
        phase=None,
        trace_json="[]",
    )


def make(
    *,
    answers: Sequence[Answer] = (VALID,),
    loop: LoopsRow | None = None,
    info: bool = True,
    agents: Sequence[str] = tuple(AGENTS),
    board_agents: Sequence[str] = (),
    preferences: Mapping[str, str] | None = None,
    repositories: Sequence[dict[str, JsonValue]] | None = None,
    runs: Sequence[LoopGenerationRunsRow] = (),
    clock: Callable[[], datetime] = lambda: MOMENT,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> World:
    state = BoardState()
    state.loops = {
        LOOP: loop or loop_row(LOOP, stage="draft"),
        OTHER: loop_row(OTHER, stage="draft").__replace__(sequence=2, key="L-2"),
    }
    state.lists = {"todo": list_row("todo", LOOP, 1024)}
    if info:
        state.documents = [document_row("info-1", LOOP, "info", content="Users must confirm.")]
    state.generation_runs = {row.id: row for row in runs}
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Delivery")
    registry.role_templates["role-org"] = role_template_row("role-org", scope="organisation")
    registry.agents = {agent_id: AGENTS[agent_id] for agent_id in agents}
    registry.agent_links = {
        (BOARD_ID, agent_id): board_agent_row(BOARD_ID, agent_id) for agent_id in board_agents
    }
    store = FakeBoardUnitOfWork(state)
    ids = Ids()
    provider = Provider(state, list(answers))
    snapshots = Snapshots(state, list(repositories or ()))
    plans = LoopPlanService(clock=lambda: MOMENT, new_id=ids)
    documents = LoopDocumentService(
        FakeBoardChecks(), store, plans, clock=lambda: MOMENT, new_id=ids
    )
    links = LoopWorkflowLinks()
    service = LoopGenerationService(
        SETTINGS,
        Boards(),
        store,
        registry_unit_of_work(registry),
        documents,
        links,
        Roles(),
        None if preferences is None else Preferences(dict(preferences)),
        None if repositories is None else snapshots,
        idempotency_ttl_seconds=3600,
        context_chars=context_chars,
        call_completion=provider,
        clock=clock,
        new_id=ids,
        background=False,
    )
    qa = QaRecorder()
    links.bind(start_generation=service.start, apply_qa_instructions=qa)
    return World(state, store, provider, snapshots, qa, service)


def start(
    w: World,
    purpose: str = "analysis",
    *,
    key: str | None = None,
    actor: ActorContext = ADA,
    **fields: JsonValue,
) -> tuple[Mapping[str, object], bool]:
    request = GenerationRequest.model_validate({"purpose": purpose, **fields})
    return w.service.start(actor, BOARD_ID, LOOP, request, idempotency_key=key)


class Later:
    """The service's clock: a run is created and started at MOMENT, and every later reading is
    ``seconds`` after it."""

    def __init__(self, seconds: int) -> None:
        self.readings = 0
        self.seconds = seconds

    def __call__(self) -> datetime:
        self.readings += 1
        return MOMENT if self.readings <= 2 else MOMENT + timedelta(seconds=self.seconds)


def approve_analysis(w: World) -> None:
    """The Loop's analysis as a person approved it, so a RoadMap may be generated."""
    w.state.documents += [
        document_row("ai-1", LOOP, "analysis_ai", info="info-1"),
        document_row("an-1", LOOP, "analysis", analysis_ai="ai-1"),
    ]
    reviewed = {"info": "info-1", "analysis_ai": "ai-1", "analysis": "an-1"}
    w.state.approvals = [
        approval_row("appr-1", LOOP, "analysis", revisions_json=json.dumps(reviewed))
    ]


def revise_info(w: World) -> None:
    """A person saves a new Info revision."""
    with w.store.writer(BOARD_ID) as repos:
        repos.documents.clear_current(LOOP, "info")
        repos.documents.add(
            document_row("info-2", LOOP, "info", revision=2, content="Users confirm twice.")
        )


# --- which agent runs ----------------------------------------------------------------------------


def test_an_explicit_agent_wins_over_the_stored_preference_and_the_default() -> None:
    w = make(preferences={"analysis": "alpha"})
    result, replayed = start(w, agent_id="beta")
    assert (result["agent_id"], result["agent_name"], result["model"], replayed) == (
        "beta",
        "Beta",
        "m-b",
        False,
    )
    assert [call.agent_id for call in w.provider.calls] == ["beta"]


def test_a_usable_stored_preference_beats_the_default() -> None:
    w = make(preferences={"analysis": "beta"})
    result, _ = start(w)
    assert result["agent_id"] == "beta"


@pytest.mark.parametrize("preferred", ["ghost", "off", "org", "beta"])
def test_a_stale_stored_preference_falls_back_to_the_board_default(preferred: str) -> None:
    # Missing, disabled, an organisation profile, and an agent that is not on this board.
    w = make(preferences={"analysis": preferred}, board_agents=("alpha",))
    result, _ = start(w)
    assert result["agent_id"] == "alpha"
    assert w.run().status == "completed"


@pytest.mark.parametrize(
    ("agent_id", "code", "message"),
    [
        ("ghost", "validation_failed", "Agent not found"),
        ("org", "agent_scope_organisation", "An organisation profile cannot run a Loop"),
        ("off", "validation_failed", "Agent is disabled"),
        ("beta", "agent_not_on_board", "That agent does not work on this board"),
    ],
)
def test_an_unusable_explicit_agent_is_refused(agent_id: str, code: str, message: str) -> None:
    w = make(board_agents=("alpha",))
    with pytest.raises(ValidationFailure) as refused:
        start(w, agent_id=agent_id)
    assert (refused.value.code, refused.value.message) == (code, message)
    assert w.state.generation_runs == {}
    assert w.provider.calls == []


def test_the_default_is_the_boards_own_agent_before_the_installations() -> None:
    assert start(make(board_agents=("beta",)))[0]["agent_id"] == "beta"
    # A board whose own agents are all unusable still runs with the installation's first one.
    assert start(make(board_agents=("off",)))[0]["agent_id"] == "alpha"


def test_without_a_usable_agent_generation_is_unavailable() -> None:
    w = make(agents=("off", "org", "legacy"))
    with pytest.raises(ServiceUnavailable) as refused:
        start(w)
    assert refused.value.code == "generation_unavailable"
    assert w.state.generation_runs == {}


def test_an_agent_whose_connection_cannot_execute_is_unavailable() -> None:
    w = make()
    with pytest.raises(ServiceUnavailable) as refused:
        start(w, agent_id="legacy")
    assert refused.value.code == "generation_unavailable"
    assert refused.value.details == {
        "connection_type": "webhook",
        "supported": ["a2a", "openai_compatible"],
    }


# --- what a run needs before it starts ----------------------------------------------------------


@pytest.mark.parametrize(
    ("purpose", "info", "code", "details"),
    [
        ("analysis", False, "document_stale", {"missing": "info"}),
        ("roadmap", True, "approval_required", {"scope": "analysis"}),
        ("qa", True, "approval_required", {"scope": "implementation"}),
    ],
)
def test_a_run_needs_its_inputs_before_it_starts(
    purpose: str, info: bool, code: str, details: dict[str, str]
) -> None:
    w = make(info=info)
    with pytest.raises(Conflict) as refused:
        start(w, purpose)
    assert (refused.value.code, refused.value.details) == (code, details)
    assert w.state.generation_runs == {}
    assert w.provider.calls == []


@pytest.mark.parametrize(
    "loop",
    [
        loop_row(LOOP, completed_at=STAMP),
        loop_row(LOOP, cancelled_at=STAMP),
        loop_row(LOOP, archived_at=STAMP),
    ],
    ids=["completed", "cancelled", "archived"],
)
def test_a_read_only_loop_refuses_a_run(loop: LoopsRow) -> None:
    w = make(loop=loop)
    with pytest.raises(Conflict) as refused:
        start(w)
    assert refused.value.code == "loop_read_only"
    assert w.state.generation_runs == {}


def test_a_run_needs_the_generate_scope() -> None:
    w = make()
    reader = ActorContext(actor_id="actor-2", actor_type="user", actor_name="Bea")
    with pytest.raises(Forbidden):
        start(w, actor=reader)
    assert w.state.generation_runs == {}


# --- a run that succeeds -------------------------------------------------------------------------


def test_an_analysis_run_is_captured_generated_and_promoted() -> None:
    w = make()
    result, replayed = start(w, instructions="Focus on sign-in.")
    run = w.run()
    captured = json.loads(run.input_json)
    # The answer is the queued run, without its captured input, role or creator.
    assert set(result) == RUN_KEYS
    assert (result["id"], result["status"], result["attempts"], replayed) == (
        "id-1",
        "queued",
        0,
        False,
    )
    assert (result["output"], result["usage"], result["source_revisions"]) == ({}, {}, SOURCES)
    assert result["input_hash"] == captured["context_hash"] == run.input_hash
    # The captured input names the board, the instructions, the agent and the documents.
    assert (captured["board_name"], captured["instructions"]) == ("Delivery", "Focus on sign-in.")
    assert captured["agent"] == {"id": "alpha", "name": "Alpha", "model": "m-1"}
    assert captured["context"]["documents"]["info"]["content"] == "Users must confirm."
    # The model got the agent's role, the purpose and the context, while the run was generating.
    (call,) = w.provider.calls
    assert (call.settings, call.agent_id) == (SETTINGS, "alpha")
    assert call.running == {"id-1": "generating"}
    assert call.system_prompt.startswith("You are alpha.\n\n")
    assert PURPOSE_PROMPTS["analysis"] in call.system_prompt
    (message,) = call.messages
    assert message["content"].startswith(
        "Purpose: analysis\nLoop: Loop loop-a (L-1)\nBoard: Delivery\n"
    )
    assert "Additional instructions: Focus on sign-in." in message["content"]
    role = json.loads(run.role_snapshot_json)
    assert (role["system_prompt"], role["role_source"], role["purpose"]) == (
        call.system_prompt,
        "template",
        "analysis",
    )
    # The run completed with what the model returned.
    assert (run.status, run.attempts, run.phase, run.error_code) == (
        "completed",
        1,
        "generating",
        None,
    )
    assert (run.started_at, run.finished_at, run.model) == (STAMP, STAMP, "m-2")
    references = {"analysis_ai": "id-2", "analysis": "id-3"}
    entry = w.service.get(BOARD_ID, LOOP, "id-1")
    assert set(entry) == RUN_KEYS
    assert entry["output"] == {**PAYLOAD, "_references": references}
    assert (entry["usage"], entry["source_revisions"]) == ({"total_tokens": 42}, SOURCES)
    # Both analysis documents carry the run and its provenance, authored by the agent.
    stored = {row.kind: row for row in w.state.documents if row.is_current}
    for kind, document_id in references.items():
        document = stored[kind]
        assert (document.id, document.generation_run_id, document.source_info_revision_id) == (
            document_id,
            "id-1",
            "info-1",
        )
        # The human view is rendered from the structure until a board agent writes it.
        rendered = {"rendered": True} if kind == "analysis" else {}
        assert json.loads(document.provenance_json) == {**PROVENANCE, **rendered}
        assert (document.author_actor_id, document.author_actor_type) == ("alpha", "agent")
    assert w.state.loops[LOOP].stage == "analysis_review"


def test_a_qa_run_hands_its_instructions_to_the_qa_workflow() -> None:
    loop = loop_row(LOOP, stage="awaiting_qa").__replace__(implementation_approval_id="appr-1")
    w = make(answers=[answer(json.dumps(QA))], loop=loop, repositories=REPOSITORIES)
    start(w, "qa")
    run = w.run()
    assert run.status == "completed"
    assert w.qa.applied == [(LOOP, QaInstructions.model_validate(QA), "id-1", PROVENANCE)]
    (call,) = w.provider.calls
    assert call.response_schema == {"name": "qa", "schema": QaInstructions.model_json_schema()}
    assert json.loads(run.output_json)["_references"] == {"cycle_id": "cycle-1"}
    # QA instructions are written from the documents; the repositories are never fetched.
    assert w.snapshots.phases == []
    assert w.kinds() == ["info"]


# --- output repair and failures ------------------------------------------------------------------


def test_invalid_output_is_repaired_by_a_second_call() -> None:
    w = make(answers=[answer("I could not do it."), VALID])
    start(w)
    first, repair = w.provider.calls
    assert w.run().status == "completed"
    assert repair.messages[:2] == [
        first.messages[0],
        {"role": "assistant", "content": "I could not do it."},
    ]
    assert repair.messages[2]["role"] == "user"
    assert repair.messages[2]["content"].startswith("That response did not validate.")
    assert w.kinds() == ["info", "analysis_ai", "analysis"]
    # Both calls hand the runtime the schema the prompt shows, for a provider that takes one.
    schema = {"name": "analysis", "schema": AnalysisPayload.model_json_schema()}
    assert first.response_schema == repair.response_schema == schema


def test_output_still_invalid_after_the_repairs_fails_for_good() -> None:
    w = make(answers=[answer('{"not": "the schema"}')] * (MAX_REPAIRS + 1))
    start(w)
    run = w.run()
    assert len(w.provider.calls) == MAX_REPAIRS + 1
    assert (run.status, run.error_code, run.finished_at) == ("failed", "invalid_output", STAMP)
    message = run.error_message or ""
    assert message.startswith("Generated output did not match the schema (")
    assert message.endswith(") (not retryable)")
    assert w.kinds() == ["info"]
    assert w.state.loops[LOOP].stage == "draft"


@pytest.mark.parametrize(
    "answers", [[FAILED], [answer("not json"), FAILED]], ids=["first call", "repair call"]
)
def test_a_provider_failure_fails_the_run_as_retryable(answers: list[Answer]) -> None:
    w = make(answers=answers)
    start(w)
    run = w.run()
    assert len(w.provider.calls) == len(answers)
    assert (run.status, run.error_code, run.error_message) == (
        "failed",
        "provider_error",
        "The provider call failed: boom",
    )
    assert w.kinds() == ["info"]


@pytest.mark.parametrize(
    ("raised", "message"),
    [
        (RuntimeError("socket closed"), "RuntimeError: socket closed"),
        (RuntimeError("x" * 600), "RuntimeError: " + "x" * MAX_EXCEPTION_TEXT),
        (TimeoutError(), "TimeoutError"),
    ],
    ids=["its text", "the start of a long text", "no text"],
)
def test_a_provider_that_raises_fails_the_run_without_breaking_the_start(
    raised: Exception, message: str
) -> None:
    w = make()
    w.provider.raises = raised
    result, _ = start(w)
    run = w.run()
    assert result["status"] == "queued"
    # The class name and what the exception says, bounded; the run may be tried again.
    assert (run.status, run.error_code, run.error_message, run.output_json) == (
        "failed",
        "generation_failed",
        message,
        "{}",
    )


def test_a_roadmap_that_breaks_a_plan_rule_is_repaired_with_the_rule_named() -> None:
    w = make(answers=[answer(json.dumps(roadmap([UNKNOWN_PHASE]))), answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    first, repair = w.provider.calls
    assert repair.messages[:2] == [
        first.messages[0],
        {"role": "assistant", "content": json.dumps(roadmap([UNKNOWN_PHASE]))},
    ]
    # The repair names the rule, the Phase and the reference that does not resolve.
    content = repair.messages[2]["content"]
    assert content.startswith("That response did not validate.")
    assert "Phase dependency references an unknown Phase" in content
    assert f'"phase_id": "{PHASE}", "missing": "{UNKNOWN_PHASE}"' in content
    run = w.run()
    assert (run.status, run.error_code) == ("completed", None)
    assert w.kinds() == ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"]


def test_a_roadmap_that_breaks_a_plan_rule_every_time_fails_with_the_last_rule() -> None:
    answers = [answer(json.dumps(roadmap([UNKNOWN_PHASE])))] * MAX_REPAIRS
    w = make(answers=[*answers, answer(json.dumps(roadmap([PHASE])))])
    approve_analysis(w)
    start(w, "roadmap")
    run = w.run()
    assert len(w.provider.calls) == MAX_REPAIRS + 1
    assert (run.status, run.error_code, run.error_message) == (
        "failed",
        "invalid_output",
        "Generated output broke a rule: A Phase cannot depend on itself (not retryable)",
    )
    entry = w.service.get(BOARD_ID, LOOP, "id-1")
    assert entry["output"] == {
        "error_details": {"rule": "invalid_dependency_graph", "phase_id": PHASE}
    }
    assert w.kinds() == ["info", "analysis_ai", "analysis"]


def test_promotion_still_refuses_a_roadmap_that_breaks_a_plan_rule() -> None:
    """The repair loop checks the rules first; promotion stays the last line of defence."""
    w = make()
    approve_analysis(w)
    broken = PlanPayload.model_validate(roadmap([UNKNOWN_PHASE]))
    with pytest.raises(ValidationFailure) as refused, w.store.writer(BOARD_ID) as repos:
        w.service.documents.store_generated_roadmap(
            repos, w.state.loops[LOOP], broken, ADA, run_id="id-1", provenance={}
        )
    assert (refused.value.code, refused.value.details) == (
        "invalid_dependency_graph",
        {"phase_id": PHASE, "missing": UNKNOWN_PHASE},
    )
    assert w.kinds() == ["info", "analysis_ai", "analysis"]


def test_a_failed_run_keeps_no_prompt_message_token_or_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = make()
    w.provider.raises = ServiceUnavailable(
        "The model refused the request",
        code="model_refused",
        details={
            "status": 400,
            "prompt": "SECRET prompt",
            "messages": [{"role": "user", "content": "SECRET message"}],
            "provider": {
                "api_key": "SECRET key",
                "Token": "SECRET token",
                "hint": "check the model",
            },
        },
    )
    with caplog.at_level(logging.DEBUG, logger="tralala"):
        start(w)
    run = w.run()
    assert (run.status, run.error_code, run.error_message) == (
        "failed",
        "model_refused",
        "The model refused the request",
    )
    assert json.loads(run.output_json) == {
        "error_details": {"status": 400, "provider": {"hint": "check the model"}}
    }
    logged = json.dumps(events(caplog.records))
    assert "generation_run_finished" in logged
    assert "SECRET" not in logged + run.output_json + (run.error_message or "")


def test_error_details_over_the_bound_are_kept_as_their_truncated_text() -> None:
    w = make()
    w.provider.raises = ServiceUnavailable(
        "Too much", code="too_much", details={"text": "y" * 3000}
    )
    start(w)
    kept = json.loads(w.run().output_json)["error_details"]
    assert isinstance(kept, str)
    assert (len(kept), kept[:10]) == (2000, '{"text": "')


@pytest.mark.parametrize(
    ("answers", "status", "error_code", "prompt_tokens", "completion_tokens"),
    [
        ([answer(json.dumps(ANALYSIS), usage=USAGE)], "completed", None, 1200, 300),
        ([FAILED], "failed", "provider_error", None, None),
    ],
    ids=["completed", "failed"],
)
def test_a_run_logs_its_start_and_its_end_once(
    caplog: pytest.LogCaptureFixture,
    answers: list[Answer],
    status: str,
    error_code: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    w = make(answers=answers, repositories=REPOSITORIES, clock=Later(3))
    with caplog.at_level(logging.INFO, logger="tralala.loop_generation"):
        start(w)
    lifecycle = [
        event
        for event in events(caplog.records)
        if event["event"] in {"generation_run_started", "generation_run_finished"}
    ]
    who = {"run_id": "id-1", "purpose": "analysis", "agent_id": "alpha"}
    assert lifecycle == [
        {"event": "generation_run_started", **who},
        {
            "event": "generation_run_finished",
            **who,
            "status": status,
            "error_code": error_code,
            "duration_ms": 3000,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "snapshot_chars": len("print('hello')"),
            # A snapshot run makes no tool call.
            "tool_calls": 0,
            "files_read": 0,
        },
    ]


def swedish_analysis(chars: int) -> dict[str, JsonValue]:
    """An analysis whose four findings hold ``chars`` characters each outside ASCII."""
    findings: list[JsonValue] = [
        {
            "id": f"F-0{number}",
            "title": "Återanvänd inloggningen",
            "category": "reuse",
            "technical_detail": "å" * chars,
            "plain_language": "Bygg ut inloggningen.",
        }
        for number in range(1, 5)
    ]
    return {"outcome": "Verifiera adresser", "findings": findings, "recommendation": "Välj."}


def test_a_kept_result_outside_ascii_is_stored_whole_and_stays_readable() -> None:
    # About 160 000 characters: escaped, six times that, which used to be cut into broken JSON.
    w = make(answers=[answer(json.dumps(swedish_analysis(40_000), ensure_ascii=False))])
    w.provider.before = lambda: revise_info(w)
    start(w)
    assert (w.run().error_code, len(w.run().output_json) <= MAX_OUTPUT_CHARS) == (
        "generation_input_changed",
        True,
    )
    # The run reads back: its answer carries the stored output parsed.
    stored: JsonValue = json.loads(w.run().output_json)
    assert w.service.get(BOARD_ID, LOOP, "id-1")["output"] == stored
    match stored:
        case {"stale_candidate": {"findings": [*_, {"technical_detail": detail}]}}:
            assert detail == "å" * 40_000
        case other:
            pytest.fail(f"no kept candidate in {str(other)[:200]}")


def test_a_promoted_result_keeps_its_text_as_written() -> None:
    w = make(answers=[answer(json.dumps(swedish_analysis(1_000), ensure_ascii=False))])
    start(w)
    assert w.run().status == "completed"
    assert "å" * 1_000 in w.run().output_json


def test_output_that_does_not_fit_is_replaced_by_a_note_never_cut() -> None:
    text = stored_output({"recommendation": "x" * MAX_OUTPUT_CHARS})
    assert json.loads(text) == {"output_omitted": True, "chars": MAX_OUTPUT_CHARS + 22}


# --- what changes while the model works ----------------------------------------------------------


def test_a_changed_input_keeps_the_result_but_promotes_nothing() -> None:
    w = make()
    w.provider.before = lambda: revise_info(w)
    start(w)
    run = w.run()
    assert (run.status, run.error_code) == ("failed", "generation_input_changed")
    assert json.loads(run.output_json) == {"stale_candidate": PAYLOAD}
    assert w.kinds() == ["info", "info"]
    assert w.state.loops[LOOP].stage == "draft"


def test_a_run_cancelled_while_the_model_works_is_not_promoted() -> None:
    w = make()

    def cancel() -> None:
        w.service.cancel(ADA, BOARD_ID, LOOP, "id-1")

    w.provider.before = cancel
    start(w)
    assert (w.run().status, w.run().output_json) == ("cancelled", "{}")
    assert w.kinds() == ["info"]


def test_a_loop_closed_while_the_model_works_fails_the_run_by_name() -> None:
    w = make()

    def close() -> None:
        with w.store.writer(BOARD_ID) as repos:
            repos.loops.complete(LOOP, history_id="history-1", now=STAMP)

    w.provider.before = close
    start(w)
    run = w.run()
    assert (run.status, run.error_code, run.error_message) == (
        "failed",
        "loop_closed",
        "This Loop is completed and read-only (not retryable)",
    )
    assert w.kinds() == ["info"]


# --- idempotency and one active run per purpose -------------------------------------------------


def test_the_same_key_and_request_replay_the_first_answer() -> None:
    w = make()
    first, replayed = start(w, key="k-1", instructions="Focus.")
    again, replayed_again = start(w, key="k-1", instructions="Focus.")
    assert (replayed, replayed_again) == (False, True)
    assert again == first
    assert list(w.state.generation_runs) == ["id-1"]
    assert len(w.provider.calls) == 1
    with pytest.raises(Conflict) as reused:
        start(w, key="k-1", instructions="Something else.")
    assert reused.value.code == "idempotency_key_reused"
    assert list(w.state.generation_runs) == ["id-1"]


def test_an_active_run_blocks_a_second_one_for_the_same_purpose() -> None:
    w = make(runs=[run_row("run-0", status="queued")])
    with pytest.raises(Conflict) as refused:
        start(w, key="k-1")
    assert (refused.value.code, refused.value.details) == (
        "generation_in_progress",
        {"purpose": "analysis"},
    )
    assert list(w.state.generation_runs) == ["run-0"]
    assert w.state.generation_runs["run-0"].status == "queued"
    assert w.state.idempotency == {}
    assert w.provider.calls == []


def test_an_active_run_of_another_purpose_does_not_block() -> None:
    w = make(runs=[run_row("run-0", status="running", purpose="qa")])
    start(w)
    assert w.run().status == "completed"


# --- cancel, retry, recover and read -------------------------------------------------------------


def test_cancel_closes_an_open_run_and_answers_a_finished_one_unchanged() -> None:
    w = make(runs=[run_row("run-0", status="queued"), run_row("run-1", status="completed")])
    cancelled = w.service.cancel(ADA, BOARD_ID, LOOP, "run-0")
    assert (cancelled["status"], cancelled["finished_at"]) == ("cancelled", STAMP)
    assert w.run("run-0").status == "cancelled"
    finished = w.run("run-1")
    assert w.service.cancel(ADA, BOARD_ID, LOOP, "run-1")["status"] == "completed"
    assert w.run("run-1") is finished
    with pytest.raises(NotFound):
        w.service.cancel(ADA, BOARD_ID, OTHER, "run-0")


@pytest.mark.parametrize("status", ["queued", "running"])
def test_retry_is_refused_while_the_run_is_active(status: str) -> None:
    w = make(runs=[run_row("run-0", status=status)])
    with pytest.raises(Conflict) as refused:
        w.service.retry(ADA, BOARD_ID, LOOP, "run-0")
    assert refused.value.code == "generation_in_progress"
    assert list(w.state.generation_runs) == ["run-0"]


def test_retry_starts_a_fresh_run_with_the_same_purpose_and_agent() -> None:
    w = make(runs=[run_row("run-0", status="failed", agent_id="beta")])
    result, replayed = w.service.retry(ADA, BOARD_ID, LOOP, "run-0")
    assert (result["id"], result["purpose"], result["agent_id"], replayed) == (
        "id-1",
        "analysis",
        "beta",
        False,
    )
    assert (w.run("run-0").status, w.run().status) == ("failed", "completed")


def test_recover_fails_every_unfinished_run_of_the_board() -> None:
    runs = [
        run_row("queued", status="queued"),
        run_row("running", status="running", purpose="qa"),
        run_row("done", status="completed", purpose="roadmap"),
        run_row("elsewhere", status="running", loop_id=OTHER),
    ]
    w = make(runs=runs)
    assert w.service.recover(BOARD_ID) == 3
    for run_id in ("queued", "running", "elsewhere"):
        run = w.run(run_id)
        assert (run.status, run.error_code, run.finished_at) == ("failed", "interrupted", STAMP)
        assert (run.error_message or "").startswith("The process stopped while this run")
    assert w.run("done") is runs[2]
    assert w.provider.calls == []


def test_runs_are_listed_newest_first_and_read_only_within_their_loop() -> None:
    w = make(
        runs=[
            run_row("old", status="completed", created_at="2026-11-01T09:00:00Z"),
            run_row("new", status="failed", purpose="qa", created_at="2026-11-03T09:00:00Z"),
            run_row("mid", status="failed", purpose="roadmap", created_at="2026-11-02T09:00:00Z"),
            run_row("elsewhere", status="completed", loop_id=OTHER),
        ]
    )
    listed = w.service.list_runs(BOARD_ID, LOOP)
    assert [entry["id"] for entry in listed] == ["new", "mid", "old"]
    assert all(set(entry) == RUN_KEYS for entry in listed)
    assert [entry["id"] for entry in w.service.list_runs(BOARD_ID, LOOP, limit=1)] == ["new"]
    assert w.service.get(BOARD_ID, OTHER, "elsewhere")["loop_id"] == OTHER
    with pytest.raises(NotFound) as missing:
        w.service.get(BOARD_ID, LOOP, "elsewhere")
    assert missing.value.message == "Generation run not found"
    with pytest.raises(NotFound) as no_loop:
        w.service.get(BOARD_ID, "loop-x", "old")
    assert no_loop.value.code == "loop_not_found"


# --- the repository snapshot ---------------------------------------------------------------------


def test_a_repository_snapshot_reaches_the_model_but_its_paths_stay_in_the_run() -> None:
    w = make(repositories=REPOSITORIES)
    start(w)
    run = w.run()
    captured = json.loads(run.input_json)
    sources = json.loads(run.source_revisions_json)
    # Fetched inside the run, in its own phase, and sent to the model with the file contents.
    assert w.snapshots.phases == ["analysing_repository"]
    assert w.provider.context()["repositories"] == REPOSITORIES
    assert "untrusted material to analyse" in w.provider.calls[0].messages[0]["content"]
    # The run's own record keeps the snapshot and the file paths; the snapshot has its own hash,
    # while the documents' hash still decides whether the result is promoted.
    assert captured["context"]["repositories"] == REPOSITORIES
    assert sources == {
        **SOURCES,
        "repositories": [
            {
                "id": "repo-1",
                "name": "acme app",
                "branch": "main",
                "commit_sha": "abc123",
                "file_count": 1,
                "truncated": True,
                "files": ["src/app.py"],
            },
            {
                "id": "repo-2",
                "name": "docs",
                "branch": None,
                "commit_sha": None,
                "file_count": 0,
                "truncated": False,
                "files": [],
                "error": "unreachable",
            },
        ],
    }
    assert run.input_hash == request_fingerprint(captured["context"])
    assert run.input_hash != captured["context_hash"]
    assert run.status == "completed"
    # The answer names each repository and its commit, never a path or a content.
    entry = w.service.get(BOARD_ID, LOOP, "id-1")
    assert entry["source_revisions"] == {
        **SOURCES,
        "repositories": [
            {
                "id": "repo-1",
                "name": "acme app",
                "branch": "main",
                "commit_sha": "abc123",
                "file_count": 1,
                "truncated": True,
            },
            {
                "id": "repo-2",
                "name": "docs",
                "branch": None,
                "commit_sha": None,
                "file_count": 0,
                "truncated": False,
                "error": "unreachable",
            },
        ],
    }
    assert "src/app.py" not in json.dumps(entry)


def test_the_manifest_reaches_the_model_but_never_the_runs_sources_or_its_answer() -> None:
    manifest: list[JsonValue] = [
        {"path": "src/app.py", "bytes": 14, "sent": True},
        {"path": "public_docs/Onboarding.md", "bytes": 9_000, "sent": False},
    ]
    entry: dict[str, JsonValue] = {**REPOSITORIES[0], "manifest": manifest, "manifest_omitted": 2}
    w = make(repositories=[entry])
    start(w)
    run = w.run()
    # The model is told which files exist, the ones it was not sent included.
    match w.provider.context()["repositories"]:
        case [{"manifest": listed, "manifest_omitted": 2}]:
            assert listed == manifest
        case other:
            pytest.fail(f"no manifest in {other!r}")
    # The run's sources keep the paths of the files sent, not the manifest; the answer neither.
    (recorded,) = json.loads(run.source_revisions_json)["repositories"]
    assert "manifest" not in recorded and "manifest_omitted" not in recorded
    assert recorded["files"] == ["src/app.py"]
    answer = json.dumps(w.service.get(BOARD_ID, LOOP, "id-1"))
    assert "manifest" not in answer and "Onboarding.md" not in answer and "src/app.py" not in answer


def test_a_board_without_a_repository_tells_the_model_so() -> None:
    w = make(repositories=[])
    start(w)
    run = w.run()
    assert w.provider.context()["repositories"] == "no enabled repository is linked to this board"
    assert (
        "Repository snapshot: no enabled repository is linked to this board."
        in (w.provider.calls[0].messages[0]["content"])
    )
    assert json.loads(run.source_revisions_json)["repositories"] == []
    assert run.status == "completed"


# --- the context budget --------------------------------------------------------------------------


def snapshot_entry(content: str, *, sha: str = "abc123", included: int | None = None) -> JsonValue:
    """One repository as the snapshot service answers under a budget, holding one file."""
    return {
        "id": "repo-1",
        "name": "acme app",
        "branch": "main",
        "commit_sha": sha,
        "file_count": 1,
        "truncated": False,
        "budget_chars": 0,
        "snapshot_chars_included": len(content) + 60 if included is None else included,
        "content_omitted": False,
        "files": [{"path": "src/app.py", "bytes": len(content), "content": content}],
    }


def previous_analysis(w: World, chars: int) -> None:
    """The Loop already holds an AI analysis of ``chars`` characters from an earlier run."""
    w.state.documents.append(
        document_row("ai-0", LOOP, "analysis_ai", info="info-1", content="a" * chars)
    )


def test_info_a_long_previous_analysis_and_a_large_snapshot_all_reach_the_model() -> None:
    code = "x" * (196 * 1024)
    entry = snapshot_entry(code)
    assert isinstance(entry, dict)
    w = make(repositories=[entry])
    previous_analysis(w, 30_000)
    start(w)
    # The documents took their room first; the rest went to the repositories.
    (budget,) = w.snapshots.budgets
    assert 196 * 1024 < budget < DEFAULT_CONTEXT_CHARS - 30_000
    context = w.provider.context()
    match context:
        case {
            "repositories": [{"files": [{"content": sent}], **rest}],
            "documents": {"info": {"content": info}, "analysis_ai": {"content": draft}},
        }:
            assert (sent, rest.get("content_omitted"), info, draft) == (
                code,
                False,
                "Users must confirm.",
                "a" * 30_000,
            )
        case other:
            pytest.fail(f"unexpected context {other!r}")


@pytest.mark.parametrize(("used", "dropped"), [(30_000, True), (0, False)], ids=["used", "unused"])
def test_previous_drafts_go_before_any_repository_file_and_the_info_stays(
    used: int, dropped: bool
) -> None:
    entry = snapshot_entry("y" * max(used - 60, 0), included=used)
    assert isinstance(entry, dict)
    w = make(repositories=[entry], context_chars=60_000)
    previous_analysis(w, 50_000)
    start(w)
    # Too little room beside the drafts: the snapshot was offered the room without them.
    (budget,) = w.snapshots.budgets
    assert budget > 50_000
    documents = w.provider.context()["documents"]
    assert isinstance(documents, dict)
    assert documents["info"] == {
        "revision_id": "info-1",
        "revision_number": 1,
        "content": "Users must confirm.",
        "payload": None,
    }
    # The drafts went only when the repositories used the room they left.
    draft = documents["analysis_ai"]
    assert isinstance(draft, dict)
    if dropped:
        assert draft == {"revision_id": "ai-0", "revision_number": 1, "content_omitted": True}
    else:
        assert draft["content"] == "a" * 50_000


def test_the_run_names_each_repositorys_budget_and_what_it_used() -> None:
    entry = snapshot_entry("print('hello')", included=75)
    assert isinstance(entry, dict)
    w = make(repositories=[{**entry, "budget_chars": 1_000}])
    start(w)
    sources = w.service.get(BOARD_ID, LOOP, "id-1")["source_revisions"]
    assert isinstance(sources, dict)
    assert sources["repositories"] == [
        {
            "id": "repo-1",
            "name": "acme app",
            "branch": "main",
            "commit_sha": "abc123",
            "file_count": 1,
            "truncated": False,
            "budget_chars": 1_000,
            "snapshot_chars_included": 75,
            "content_omitted": False,
        }
    ]


def test_a_mirrored_repository_says_how_it_was_read_and_that_its_mirror_was_stale() -> None:
    entry = snapshot_entry("print('hello')", included=75)
    assert isinstance(entry, dict)
    stale = {
        **entry,
        "provider": "git_https",
        "fetched_at": "2026-11-02T08:00:00Z",
        "stale_mirror": True,
        "fetch_error": "timeout",
    }
    w = make(repositories=[stale])
    start(w)
    named = {
        "id": "repo-1",
        "name": "acme app",
        "branch": "main",
        "commit_sha": "abc123",
        "provider": "git_https",
        "fetched_at": "2026-11-02T08:00:00Z",
        "stale_mirror": True,
        "file_count": 1,
        "truncated": False,
        "budget_chars": 0,
        "snapshot_chars_included": 75,
        "content_omitted": False,
    }
    # The run's own record keeps the file paths beside it; the answer names the repository only.
    recorded = json.loads(w.run().source_revisions_json)["repositories"]
    assert recorded == [{**named, "files": ["src/app.py"]}]
    sources = w.service.get(BOARD_ID, LOOP, "id-1")["source_revisions"]
    assert isinstance(sources, dict)
    assert sources["repositories"] == [named]


def test_two_commits_of_the_same_repository_are_different_inputs() -> None:
    hashes: list[str] = []
    for sha in ("abc123", "def456"):
        entry = snapshot_entry("print('hello')", sha=sha)
        assert isinstance(entry, dict)
        w = make(repositories=[entry])
        start(w)
        hashes.append(w.run().input_hash)
    assert hashes[0] != hashes[1]



# --- the analysis written for people -------------------------------------------------------------

MATERIAL = AnalysisPayload.model_validate(
    {
        "outcome": "Verify addresses",
        "findings": [
            {
                "id": "F-01",
                "title": "Reuse auth",
                "category": "reuse",
                "technical_detail": "auth.py",
                "plain_language": "Extend sign-in.",
            },
            {
                "id": "F-02",
                "title": "Bounces",
                "category": "risk",
                "technical_detail": "No bounce handling in the mailer.",
                "plain_language": "Some e-mails never arrive.",
            },
            {
                "id": "F-03",
                "title": "Wording",
                "category": "question",
                "technical_detail": "No copy for the mail exists.",
                "plain_language": "Someone has to write the e-mail.",
            },
        ],
    }
)
WRITTEN = "People confirm by e-mail. Some never arrive [F-02]; who writes it is open [F-03]."
HALF = "People confirm by e-mail. Some never arrive [F-02]."
SAVED_FOR_PEOPLE = "Saved the analysis for people as a draft for a person to review and approve"


def with_technical_analysis(w: World) -> None:
    """The Loop's technical analysis ``ai-1`` from ``info-1``, and the view rendered from it."""
    w.state.documents += [
        document_row("ai-1", LOOP, "analysis_ai", info="info-1").__replace__(
            payload_json=json.dumps(MATERIAL.model_dump())
        ),
        document_row("an-1", LOOP, "analysis", analysis_ai="ai-1").__replace__(
            provenance_json='{"rendered": true}'
        ),
    ]


def human_view(w: World) -> LoopDocumentsRow:
    return next(row for row in w.state.documents if row.kind == "analysis" and row.is_current)


def steps(w: World, run_id: str = "id-1") -> list[tuple[object, object]]:
    """The run's trace as (kind, text) pairs."""
    loaded = parse_steps(w.run(run_id).trace_json)
    return [(step.get("kind"), step.get("text")) for step in loaded if isinstance(step, dict)]


def wire(w: World) -> None:
    """As the composition root does: a new technical analysis is written for people."""
    w.service.documents.human_view = w.service.start_human_view


def submit_analysis(w: World) -> DocumentsView:
    candidate = CandidateSubmission(
        kind="analysis", analysis=AnalysisPayload.model_validate(ANALYSIS)
    )
    return w.service.documents.submit_candidate(ADA, BOARD_ID, LOOP, candidate)


def test_the_analysis_is_written_for_people_with_the_servers_traceability_block() -> None:
    w = make(answers=[answer(WRITTEN)])
    with_technical_analysis(w)
    start(w, "analysis_human")
    assert (w.run().status, w.run().purpose) == ("completed", "analysis_human")
    human = human_view(w)
    assert human.content == compose_human_view(WRITTEN, MATERIAL)
    assert human.content.endswith(render_traceability(MATERIAL))
    assert json.loads(human.provenance_json) == {**PROVENANCE, "written": True}
    assert (human.source_analysis_ai_revision_id, human.source_info_revision_id) == (
        "ai-1",
        "info-1",
    )
    assert (human.author_actor_id, human.generation_run_id) == ("alpha", "id-1")
    # A text answer: no schema, no tools, and only the Info and the analysis it explains.
    (call,) = w.provider.calls
    assert call.response_schema is None
    assert call.system_prompt == f"You are alpha.\n\n{PURPOSE_PROMPTS['analysis_human']}"
    message = call.messages[0]["content"]
    assert "Users must confirm." in message
    assert '"id": "F-03"' in message
    assert "Context (JSON)" not in message
    assert call.running == {"id-1": "writing_for_people"}
    assert ("step", "The text names every material finding") in steps(w)
    assert ("step", SAVED_FOR_PEOPLE) in steps(w)


def test_a_text_that_leaves_a_finding_out_is_sent_back_once_with_its_id() -> None:
    w = make(answers=[answer(HALF), answer(WRITTEN)])
    with_technical_analysis(w)
    start(w, "analysis_human")
    assert w.run().status == "completed"
    repair = w.provider.calls[1].messages
    assert repair[1] == {"role": "assistant", "content": HALF}
    assert "F-03" in str(repair[2]["content"])
    assert "F-02" not in str(repair[2]["content"])
    assert ("repair", "The text leaves out F-03 — asked the model to cover them") in steps(w)
    assert human_view(w).content.startswith(WRITTEN)


def test_a_text_that_still_leaves_one_out_fails_and_the_rendered_view_stays() -> None:
    w = make(answers=[answer(HALF), answer(HALF)])
    with_technical_analysis(w)
    start(w, "analysis_human")
    run = w.run()
    assert (run.status, run.error_code) == ("failed", "coverage_missing")
    assert json.loads(run.output_json) == {"error_details": {"finding_ids": ["F-03"]}}
    assert "(not retryable)" not in (run.error_message or "")
    assert human_view(w).id == "an-1"


def test_an_empty_answer_counts_as_leaving_everything_out() -> None:
    w = make(answers=[answer("  "), answer("```\n```")])
    with_technical_analysis(w)
    start(w, "analysis_human")
    assert (w.run().status, w.run().error_code) == ("failed", "coverage_missing")
    assert "F-02, F-03" in str(w.provider.calls[1].messages[2]["content"])


def test_writing_for_people_needs_a_technical_analysis_nobody_approved_yet() -> None:
    w = make()
    with pytest.raises(Conflict) as empty:
        start(w, "analysis_human")
    assert (empty.value.code, empty.value.details) == ("document_empty", {"kind": "analysis_ai"})
    with_technical_analysis(w)
    reviewed = {"info": "info-1", "analysis_ai": "ai-1", "analysis": "an-1"}
    w.state.approvals = [
        approval_row("appr-1", LOOP, "analysis", revisions_json=json.dumps(reviewed))
    ]
    with pytest.raises(Conflict) as approved:
        start(w, "analysis_human")
    assert approved.value.code == "approval_exists"
    assert approved.value.details == {"scope": "analysis"}
    assert w.state.generation_runs == {}


def test_the_analysis_is_written_for_people_by_the_loops_analysis_agent() -> None:
    w = make(answers=[answer(WRITTEN)], preferences={"analysis": "beta", "roadmap": "alpha"})
    with_technical_analysis(w)
    start(w, "analysis_human")
    assert w.run().agent_id == "beta"


def test_a_generated_analysis_is_written_for_people_by_a_run_of_its_own() -> None:
    w = make(answers=[VALID, answer("People confirm their address by e-mail.")])
    wire(w)
    start(w)
    analysis_run, written_run = w.state.generation_runs.values()
    assert (analysis_run.purpose, analysis_run.status) == ("analysis", "completed")
    assert (written_run.purpose, written_run.status) == ("analysis_human", "completed")
    assert (written_run.created_by_actor_id, written_run.created_by_actor_type) == (
        "actor-1",
        "user",
    )
    assert steps(w, analysis_run.id)[-1] == ("note", "A board agent writes it for people next")
    human = human_view(w)
    assert human.content.startswith("People confirm their address by e-mail.")
    assert json.loads(human.provenance_json)["generation_run_id"] == written_run.id
    assert len(w.provider.calls) == 2


def test_a_submitted_analysis_is_written_for_people_once() -> None:
    w = make(answers=[answer("People confirm their address by e-mail.")])
    wire(w)
    view = submit_analysis(w)
    (run,) = w.state.generation_runs.values()
    assert run.purpose == "analysis_human"
    assert view.get("human_view") == {"status": "completed", "run_id": run.id}
    assert view["documents"]["analysis"]["current_provenance"].get("written") is True


def test_without_an_agent_the_rendered_view_stays_and_the_skip_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = make(agents=(), answers=[])
    wire(w)
    with caplog.at_level(logging.INFO, logger="tralala.loop_generation"):
        view = submit_analysis(w)
    assert view.get("human_view") == {
        "status": "skipped",
        "run_id": None,
        "reason": "generation_unavailable",
    }
    assert {
        "event": "human_view_skipped",
        "board_id": BOARD_ID,
        "loop_id": LOOP,
        "reason": "generation_unavailable",
    } in events(caplog.records)
    assert view["documents"]["analysis"]["current_provenance"].get("rendered") is True


def test_a_view_already_being_written_is_not_started_twice() -> None:
    w = make(runs=[run_row("busy", status="running", purpose="analysis_human")])
    with_technical_analysis(w)
    started = w.service.start_human_view(ADA, BOARD_ID, LOOP)
    assert started == {"status": "skipped", "run_id": None, "reason": "generation_in_progress"}
    assert list(w.state.generation_runs) == ["busy"]
