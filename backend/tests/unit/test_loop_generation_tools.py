"""A generation run whose model reads the repositories through tools, on the in-memory fakes.

The provider is scripted: each answer calls tools or answers in text, and every call it receives is
recorded with its messages, the tools it was offered and the tool choice. The repositories are
in-memory tarballs, so the workspace the model reads is the real one; nothing touches a disk, the
network or a thread.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import pytest
from pydantic import JsonValue

from app.db.generated.board import LoopGenerationRunsRow
from app.schemas.loops import GenerationRequest
from app.services.loop_documents import LoopDocumentService
from app.services.loop_generation import LoopGenerationService
from app.services.loop_generation_prompts import DEFAULT_CONTEXT_CHARS, REPOSITORY_TOOLS
from app.services.loop_generation_runs import serialize_run
from app.services.loop_generation_tools import (
    NO_MORE_CALLS,
    SET_ASIDE_MARK,
    conversation_chars,
    set_aside_oldest,
    workspace_tools,
)
from app.services.loop_generation_trace import counts_of, documents_step, parse_steps
from app.services.loop_links import LoopWorkflowLinks
from app.services.loop_plans import LoopPlanService
from app.services.repo_snapshot import FetchedRepository
from app.services.repository_problems import problem_text
from app.services.runtime import Completion, ResponseSchema
from app.services.runtime_tools import ChatMessage, Message, ToolCall, ToolChoice, ToolDefinition
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    document_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import RegistryState, agent_row, board_row, registry_unit_of_work
from tests.unit.log_lines import events
from tests.unit.test_loop_generation_service import (
    ADA,
    ANALYSIS,
    LOOP,
    MOMENT,
    SETTINGS,
    Boards,
    Ids,
    QaRecorder,
    Roles,
)

SHA = "a" * 40
# File content the trace must never hold: it records what was asked for, never what was read.
MARKER = "CONTENT-THAT-STAYS-IN-THE-REPOSITORY"
FILES = {
    "README.md": b"# Acme\nSee docs/install.md for the setup.\n",
    "docs/install.md": f"Install with pip.\n{MARKER}\n".encode(),
    "src/main.py": b"def main():\n    return 'hello'\n",
}
SNAPSHOT_ENTRY: dict[str, JsonValue] = {
    "id": "repo-1",
    "name": "app",
    "commit_sha": SHA,
    "file_count": 1,
    "truncated": True,
    "manifest": [{"path": "README.md", "bytes": 40, "sent": True}],
    "files": [{"path": "README.md", "bytes": 40, "content": "# Acme"}],
}


def tarball(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path, payload in files.items():
            info = tarfile.TarInfo(f"acme-app-{SHA[:7]}/{path}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return gzip.compress(buffer.getvalue(), mtime=0)


def fetched_app(files: Mapping[str, bytes] = FILES) -> FetchedRepository:
    entry: dict[str, JsonValue] = {
        "id": "repo-1",
        "name": "app",
        "branch": "main",
        "commit_sha": SHA,
    }
    return FetchedRepository(entry, tarball(files))


def tool(name: str, arguments: JsonValue, call_id: str = "c1") -> ToolCall:
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "arguments_error": None,
        "arguments_text": json.dumps(arguments),
    }


def calls(*made: ToolCall, text: str = "") -> Completion:
    return {
        "ok": True,
        "error": None,
        "text": text,
        "tool_calls": list(made),
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        "model": "m-2",
    }


def answer(text: str) -> Completion:
    return calls(text=text)


VALID = answer(json.dumps(ANALYSIS))


@dataclass(slots=True)
class Seen:
    messages: list[Message]
    tools: list[str]
    tool_choice: ToolChoice
    response_schema: ResponseSchema | None


@dataclass
class ToolProvider:
    """The provider, scripted; ``before`` runs ahead of the call it is numbered for (1 is the
    first), as a person could act while the model works."""

    answers: list[Completion]
    seen: list[Seen] = field(default_factory=list[Seen])
    before: dict[int, Callable[[], None]] = field(default_factory=dict[int, Callable[[], None]])

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
    ) -> Completion:
        del settings, agent_row, system_prompt
        offered = [definition["name"] for definition in tools or ()]
        self.seen.append(Seen(list(messages), offered, tool_choice, response_schema))
        hook = self.before.pop(len(self.seen), None)
        if hook is not None:
            hook()
        return self.answers.pop(0)


@dataclass
class Repositories:
    """The board's repositories: fetched with their archives, or read as a snapshot."""

    fetched: list[FetchedRepository]
    entries: list[dict[str, JsonValue]] = field(default_factory=lambda: [dict(SNAPSHOT_ENTRY)])
    fetches: int = 0
    boards: int = 0
    snapshots: int = 0

    def for_board(self, board_id: str, *, budget_chars: int) -> Sequence[Mapping[str, JsonValue]]:
        del board_id, budget_chars
        self.boards += 1
        return self.entries

    def fetch(self, board_id: str) -> Sequence[FetchedRepository]:
        del board_id
        self.fetches += 1
        return self.fetched

    def snapshot_of(
        self, fetched: Sequence[FetchedRepository], *, budget_chars: int
    ) -> Sequence[Mapping[str, JsonValue]]:
        del fetched, budget_chars
        self.snapshots += 1
        return self.entries


@dataclass(slots=True)
class World:
    state: BoardState
    provider: ToolProvider
    repositories: Repositories
    service: LoopGenerationService

    def run(self) -> LoopGenerationRunsRow:
        return self.state.generation_runs["id-1"]

    def steps(self) -> list[dict[str, JsonValue]]:
        return [step for step in parse_steps(self.run().trace_json) if isinstance(step, dict)]

    def texts(self, kind: str | None = None) -> list[str]:
        return [
            str(step["text"]) for step in self.steps() if kind is None or step.get("kind") == kind
        ]


def make(
    answers: Sequence[Completion],
    *,
    supports_tools: bool = True,
    connection_type: str = "openai_compatible",
    fetched: Sequence[FetchedRepository] | None = None,
    tool_steps: int = 60,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> World:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="draft")}
    state.lists = {"todo": list_row("todo", LOOP, 1024)}
    state.documents = [document_row("info-1", LOOP, "info", content="Improve onboarding.")]
    registry = RegistryState()
    registry.boards[BOARD_ID] = board_row(BOARD_ID, name="Delivery")
    registry.agents = {
        "reader": agent_row(
            "reader",
            name="Reader",
            model="m-1",
            connection_type=connection_type,
            supports_tools=supports_tools,
        )
    }
    store = FakeBoardUnitOfWork(state)
    ids = Ids()
    provider = ToolProvider(list(answers))
    repositories = Repositories(list(fetched if fetched is not None else [fetched_app()]))
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
        None,
        repositories,
        idempotency_ttl_seconds=3600,
        context_chars=context_chars,
        tool_steps=tool_steps,
        call_completion=provider,
        clock=lambda: MOMENT,
        new_id=ids,
        background=False,
    )
    links.bind(start_generation=service.start, apply_qa_instructions=QaRecorder())
    return World(state, provider, repositories, service)


def start(w: World) -> None:
    request = GenerationRequest.model_validate({"purpose": "analysis", "agent_id": "reader"})
    w.service.start(ADA, BOARD_ID, LOOP, request)


def stages(w: World) -> list[str]:
    """The tree's top level: each stage once, in the order the run reached it."""
    seen: list[str] = []
    for step in w.steps():
        stage = str(step["stage"])
        if not seen or seen[-1] != stage:
            seen.append(stage)
    return seen


# --- reading -------------------------------------------------------------------------------------


def test_the_model_reads_what_it_needs_and_the_run_keeps_the_tree(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="tralala.loop_generation")
    w = make(
        [
            calls(tool("list_files", {"glob": "*.md"}), text="I'll start with the documentation."),
            calls(tool("read_file", {"path": "app/docs/install.md"})),
            calls(tool("search", {"pattern": "main"})),
            VALID,
        ]
    )
    start(w)
    assert w.run().status == "completed"
    assert [row.kind for row in w.state.documents] == ["info", "analysis_ai", "analysis"]
    assert stages(w) == ["documents", "repository", "writing", "checking", "saving"]
    assert w.texts("tool") == [
        "Listed files matching *.md (2 files)",
        "Read app/docs/install.md, lines 1\u20132 of 2",
        "Searched for 'main': 1 match in 1 file",
    ]
    assert w.texts("note") == ["I'll start with the documentation."]
    assert w.texts()[0] == "Read the Loop's Info (revision 1)"
    assert w.texts()[-1] == "Saved the analysis as a draft for a person to review and approve"
    # The tree says what was read, never what it said.
    assert MARKER not in w.run().trace_json
    assert counts_of(parse_steps(w.run().trace_json)) == {
        "tool_calls": 3,
        "files_read": 1,
        "searches": 1,
        "listings": 1,
        "repairs": 0,
    }
    assert serialize_run(w.run())["trace"] == parse_steps(w.run().trace_json)
    (finished,) = [e for e in events(caplog.records) if e["event"] == "generation_run_finished"]
    assert (finished["tool_calls"], finished["files_read"], finished["prompt_tokens"]) == (
        3,
        1,
        400,
    )


def test_the_request_offers_the_tools_and_lists_every_file_without_its_content() -> None:
    w = make([calls(tool("read_file", {"path": "app/README.md"})), VALID])
    start(w)
    first, second = w.provider.seen
    assert first.tools == ["list_files", "read_file", "search"]
    assert (first.tool_choice, first.response_schema) == ("auto", None)
    request = first.messages[0]["content"]
    assert REPOSITORY_TOOLS in request
    assert "app/docs/install.md" in request and "app/src/main.py" in request
    assert MARKER not in request
    # The second call repeats the model's call and carries its answer.
    assert [message["role"] for message in second.messages] == ["user", "assistant", "tool"]
    assert "See docs/install.md" in second.messages[2]["content"]
    captured = json.loads(w.run().input_json)
    assert captured["repository_reading"] == "tools"
    assert captured["context"]["repositories"][0]["file_count"] == 3
    public: JsonValue = json.loads(json.dumps(serialize_run(w.run())["source_revisions"]))
    match public:
        case {"repositories": [{"reading": reading, "file_count": count, "left_out": left}]}:
            assert (reading, count, left) == ("tools", 3, 0)
        case other:
            pytest.fail(f"no repository read through tools in {other!r}")


def test_the_step_limit_asks_for_the_answer_and_says_so() -> None:
    w = make(
        [
            calls(tool("list_files", {})),
            calls(
                tool("read_file", {"path": "app/README.md"}, "c2"),
                tool("read_file", {"path": "app/src/main.py"}, "c3"),
            ),
            VALID,
        ],
        tool_steps=2,
    )
    start(w)
    assert w.run().status == "completed"
    assert len(w.texts("tool")) == 2
    assert w.texts("limit") == [
        "Reached the 2 tool calls this run allows; asked the model for its answer now"
    ]
    last = w.provider.seen[-1]
    assert last.tool_choice == "none"
    assert last.messages[-2] == {"role": "tool", "tool_call_id": "c3", "content": NO_MORE_CALLS}
    assert "You have made the 2 tool calls this run allows" in last.messages[-1]["content"]


def test_a_model_that_keeps_calling_tools_after_the_limit_fails_in_words() -> None:
    listing = calls(tool("list_files", {}))
    w = make([listing, listing, listing], tool_steps=1)
    start(w)
    assert (w.run().status, w.run().error_code) == ("failed", "invalid_output")
    assert w.texts()[-1] == (
        "Nothing was saved: The model kept calling tools after this run's tool calls were used up"
    )


def test_older_answers_are_set_aside_to_stay_within_the_context() -> None:
    long = "".join(f"{index:04d} {'x' * 95}\n" for index in range(450)).encode()
    fetched = [fetched_app({**FILES, "docs/long.md": long})]
    read = calls(tool("read_file", {"path": "app/docs/long.md"}))
    w = make([read, read, VALID], fetched=fetched, context_chars=80_000)
    start(w)
    assert w.run().status == "completed"
    third = w.provider.seen[2]
    tool_answers = [message["content"] for message in third.messages if message["role"] == "tool"]
    assert tool_answers[0].startswith(SET_ASIDE_MARK) and not tool_answers[1].startswith("[")
    assert w.texts("limit") == [
        "Older tool answers were set aside to stay within the model's context window; it can "
        "read them again"
    ]
    assert "1 older tool answers were set aside" in w.texts()[-3]


def test_a_tool_error_is_an_answer_and_the_run_goes_on() -> None:
    w = make([calls(tool("read_file", {"path": "app/docs/missing.md"})), VALID])
    start(w)
    assert w.run().status == "completed"
    assert w.provider.seen[1].messages[2]["content"].startswith("Error: ")
    assert w.texts("tool") == ["Asked for app/docs/missing.md, which does not exist"]


def test_arguments_that_are_not_json_are_answered_as_an_error() -> None:
    broken: ToolCall = {
        "id": "c1",
        "name": "read_file",
        "arguments": None,
        "arguments_error": "Expecting value",
        "arguments_text": "{oops",
    }
    w = make([calls(broken), VALID])
    start(w)
    assert w.run().status == "completed"
    assert (
        w.provider.seen[1]
        .messages[2]["content"]
        .startswith("Error: the arguments of read_file are not valid JSON")
    )
    assert w.texts("tool") == ["Called read_file with arguments that were not JSON"]


def test_an_answer_that_breaks_a_rule_is_repaired_inside_the_conversation() -> None:
    w = make([calls(tool("list_files", {})), answer("not json"), VALID])
    start(w)
    assert w.run().status == "completed"
    (repair,) = w.texts("repair")
    assert repair.startswith("The answer broke a rule: ") and "asked the model to fix it" in repair
    last = w.provider.seen[-1]
    assert last.tool_choice == "auto"
    assert last.messages[-2] == {"role": "assistant", "content": "not json"}
    assert last.messages[-1]["content"].startswith("That response did not validate.")
    assert "The model wrote a corrected answer after 1 tool call" in w.texts()[-3]


def test_cancelling_the_run_stops_the_reading() -> None:
    w = make([calls(tool("list_files", {})), calls(tool("list_files", {}, "c2")), VALID])

    def cancel() -> None:
        w.state.generation_runs["id-1"] = w.run().__replace__(status="cancelled")

    w.provider.before[2] = cancel
    start(w)
    assert w.run().status == "cancelled"
    assert len(w.provider.seen) == 2
    assert w.texts()[-1] == "Not saved: the run was cancelled"


# --- the fixed snapshot instead ------------------------------------------------------------------


def test_an_agent_without_tools_reads_the_fixed_snapshot() -> None:
    w = make([VALID], supports_tools=False)
    start(w)
    assert (w.repositories.boards, w.repositories.fetches) == (1, 0)
    (seen,) = w.provider.seen
    assert seen.tools == [] and seen.response_schema is not None
    assert (
        "Sent a fixed selection of app @ aaaaaaaa: 1 of 1 file, the rest by name only (the "
        "agent's provider does not take tools; its connection test says so)"
    ) in w.texts()
    assert json.loads(w.run().input_json)["repository_reading"] == "snapshot"


def test_an_a2a_agent_reads_the_snapshot_even_when_flagged() -> None:
    w = make([VALID], connection_type="a2a")
    start(w)
    assert (w.repositories.boards, w.repositories.fetches) == (1, 0)
    assert any("an A2A agent cannot be offered tools" in text for text in w.texts())


def test_a_provider_that_refuses_the_tools_gets_the_snapshot_of_what_was_fetched() -> None:
    refused: Completion = {
        "ok": False,
        "error": "tools_refused: HTTP 400: this model does not support tools",
        "text": "",
        "tool_calls": [],
    }
    w = make([refused, VALID])
    start(w)
    assert w.run().status == "completed"
    assert (w.repositories.fetches, w.repositories.snapshots, w.repositories.boards) == (1, 1, 0)
    assert w.provider.seen[1].tools == []
    (limit,) = w.texts("limit")
    assert limit.startswith("The provider refused tool calls")


def test_with_nothing_readable_the_run_says_so_once_and_sends_no_tools() -> None:
    gone = FetchedRepository({"id": "repo-1", "name": "app", "error": "unreachable"}, None)
    w = make([VALID], fetched=[gone])
    w.repositories.entries = [{"id": "repo-1", "name": "app", "error": "unreachable"}]
    start(w)
    assert w.provider.seen[0].tools == []
    assert w.texts("error").count(problem_text("unreachable", "app")) == 1


# --- the pieces ----------------------------------------------------------------------------------


def test_the_tools_are_offered_as_the_runtime_takes_them() -> None:
    assert [definition["name"] for definition in workspace_tools()] == [
        "list_files",
        "read_file",
        "search",
    ]
    assert all(definition["parameters"]["type"] == "object" for definition in workspace_tools())


def test_the_oldest_tool_answers_go_first_and_a_set_aside_one_stays_set_aside() -> None:
    messages: list[ChatMessage] = [
        {"role": "user", "content": "u" * 10},
        {"role": "assistant", "content": "", "tool_calls": [tool("read_file", {"path": "a"})]},
        {"role": "tool", "tool_call_id": "c1", "content": "a" * 1000},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [tool("read_file", {"path": "b"}, "c2")],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "b" * 1000},
    ]
    before = conversation_chars("system", messages)
    assert before == len("system") + 10 + 2000 + 2 * (len("read_file") + len('{"path": "a"}'))
    assert set_aside_oldest(messages, "system", before - 500) == 1
    assert messages[2]["content"].startswith(SET_ASIDE_MARK)
    assert messages[4]["content"] == "b" * 1000
    assert set_aside_oldest(messages, "system", 10) == 1  # only the one left
    assert set_aside_oldest(messages, "system", 10) == 0


def test_the_documents_step_names_what_the_run_read() -> None:
    context: dict[str, JsonValue] = {
        "documents": {
            "info": {"revision_number": 3},
            "analysis_ai": {"revision_number": 2},
            "analysis": None,
        },
        "plan": {"phases": [{"tickets": [{}, {}]}, {"tickets": []}]},
    }
    assert documents_step(context) == (
        "Read the Loop's Info (revision 3), the analysis draft (revision 2) and the plan "
        "(2 Phases, 2 Tickets)"
    )
    assert documents_step({}) == "Read the Loop's goal; it has no documents yet"
