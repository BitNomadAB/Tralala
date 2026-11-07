"""A generation run whose model reads the repositories through tools (decision 0025).

An agent whose connection test found tool calling (``agents.supports_tools``) gets the Loop's
documents, the list of every file in the board's repositories at the run's commit and three
read-only tools (``repo_workspace``): it reads what the request needs, as often as it needs, and the
run ends when it answers without a tool call. That answer goes through the same parse and repair
rounds as a single call (``loop_generation_ask``).

Two kinds of limit remain, and both are settings, not rules the model is told to obey:

- *security*: the tools only read an in-memory index of the commit's archive; nothing from a
  repository is executed or written, and its text is data;
- *the model's context window*: one tool answer is at most ``tool_result_chars`` characters (a long
  file comes in parts), the conversation stays under ``context_chars`` by setting the oldest tool
  answers aside (the model can read them again), and at most ``tool_steps`` tool calls are answered
  before the model is asked for its answer.

Every tool call, every note the model writes beside one, every repair round and every limit that
applies is a step of the run's process tree (``loop_generation_trace``), written as it happens.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from pydantic import JsonValue, ValidationError

from ..core.errors import ValidationFailure
from ..db.generated.registry import AgentsRow
from ..repositories.board import BoardUnitOfWork
from .loop_generation_ask import (
    MAX_REPAIRS,
    CompletionCall,
    call_failed,
    gave_up,
    invalid_outcome,
    problem_of,
    repair_request,
    repair_step,
)
from .loop_generation_prompts import JsonObject, context_labels, parse_output, user_message
from .loop_generation_runs import MIRROR_FIELDS, Outcome, write_input
from .loop_generation_trace import (
    RunTrace,
    clip,
    note,
    repository_unreadable,
    unread_summary,
    workspace_step,
)
from .repo_snapshot import FetchedRepository, log_empty
from .repo_snapshot_select import empty_reason
from .repo_workspace import TOOL_DEFINITIONS, RepositoryWorkspace, ToolAnswer, WorkspaceSource
from .repository_problems import error_fields, unread
from .runtime import Completion
from .runtime_tools import (
    TOOLS_REFUSED,
    ChatMessage,
    ToolCall,
    ToolDefinition,
    assistant_message,
    tool_message,
)

TOOLS_REFUSED_CODE = "tools_refused"
# The defaults of TRALALA_GENERATION_TOOL_STEPS and TRALALA_GENERATION_TOOL_RESULT_CHARS.
DEFAULT_TOOL_STEPS = 60
DEFAULT_TOOL_RESULT_CHARS = 60_000
STEP_LIMIT_REQUEST = (
    "You have made the {steps} tool calls this run allows. Answer now with the JSON object alone, "
    "without a tool call, from what you have read; put what you could not read under "
    "open_questions."
)
NO_MORE_CALLS = "Not run: this run allows no more tool calls. Answer with the JSON object now."
SET_ASIDE_MARK = "[Set aside"
SET_ASIDE = (
    SET_ASIDE_MARK + " to stay within the model's context window: this answer had {chars} "
    "characters. Call the tool again to read it.]"
)


@dataclass(frozen=True, slots=True)
class ReadingLimits:
    """The context window's settings: the conversation's characters
    (``TRALALA_GENERATION_CONTEXT_CHARS``), the tool calls one run answers
    (``TRALALA_GENERATION_TOOL_STEPS``) and the characters of one tool answer
    (``TRALALA_GENERATION_TOOL_RESULT_CHARS``)."""

    context_chars: int
    tool_steps: int
    tool_result_chars: int


def workspace_tools() -> list[ToolDefinition]:
    """The workspace's tools as the runtime offers them."""
    tools: list[ToolDefinition] = []
    for definition in TOOL_DEFINITIONS:
        function = definition.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        description = function.get("description")
        parameters = function.get("parameters")
        if isinstance(name, str) and isinstance(description, str) and isinstance(parameters, dict):
            tools.append({"name": name, "description": description, "parameters": parameters})
    return tools


# --- opening the repositories ----------------------------------------------------------------


def open_workspace(
    fetched: Sequence[FetchedRepository], *, result_chars: int, trace: RunTrace
) -> tuple[list[JsonValue], RepositoryWorkspace | None]:
    """The repositories a run fetched as the model's workspace, and one entry per repository for
    the run's context: how many files the model can read and what could not be read.

    No workspace when no repository could be read at all; the run then sends what the snapshot
    says about them instead.
    """
    readable = [item for item in fetched if item.archive is not None]
    sources = [
        WorkspaceSource(
            str(item.entry.get("name") or "repository"),
            str(item.entry.get("commit_sha") or ""),
            item.archive or b"",
            item.focus,
            item.exclude,
        )
        for item in readable
    ]
    workspace = RepositoryWorkspace(sources, max_chars=result_chars)
    manifests = iter(workspace.manifest())
    entries: list[JsonValue] = []
    opened = 0
    for item in fetched:
        if item.archive is None:
            entries.append(item.entry)
            trace.add("repository", "error", repository_unreadable(item.entry))
            continue
        manifest = next(manifests)
        entry: JsonObject = {
            **item.entry,
            "name": manifest.name,
            "reading": "tools",
            "file_count": manifest.files,
            "text_bytes": manifest.bytes,
            "left_out": manifest.left_out,
        }
        if manifest.error is None and manifest.files == 0 and manifest.left_out == 0:
            # Nothing to read is a failed read, never a quiet empty workspace.
            code = empty_reason(item.archive, item.focus, item.exclude)
            log_empty(entry, code, item.started)
            entry = unread(entry, code)
        elif manifest.error is not None:
            entry = unread(entry, manifest.error)
        if entry.get("error"):
            trace.add("repository", "error", repository_unreadable(entry))
        else:
            opened += 1
            trace.add(
                "repository",
                "step",
                workspace_step(
                    manifest.name,
                    manifest.commit_sha,
                    manifest.files,
                    manifest.bytes,
                    manifest.left_out,
                ),
            )
        entries.append(entry)
    summary = unread_summary(entries)
    if summary is not None:
        trace.add("repository", *summary)
    return entries, workspace if opened else None


def attach_workspace(
    board_id: str,
    loop_id: str,
    run_id: str,
    captured: JsonObject,
    entries: list[JsonValue],
    *,
    store: BoardUnitOfWork,
) -> JsonObject:
    """The captured context with the repositories as the model reads them, written to the run:
    what each holds and how it was read, never a file's content."""
    source = captured.get("context")
    context: JsonObject = dict(source) if isinstance(source, dict) else {}
    context["repositories"] = entries
    known = captured.get("source_revisions")
    sources: JsonObject = dict(known) if isinstance(known, dict) else {}
    sources["repositories"] = [_described(entry) for entry in entries]
    captured = {
        **captured,
        "context": context,
        "source_revisions": sources,
        "repository_reading": "tools",
    }
    write_input(board_id, loop_id, run_id, captured, sources, store=store)
    return captured


def _described(entry: JsonValue) -> JsonValue:
    if not isinstance(entry, dict):
        return entry
    left_out = entry.get("left_out")
    return {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "branch": entry.get("branch"),
        "commit_sha": entry.get("commit_sha"),
        **{name: entry[name] for name in MIRROR_FIELDS if name in entry},
        "reading": entry.get("reading", "tools"),
        "file_count": entry.get("file_count", 0),
        "left_out": left_out if isinstance(left_out, int) else 0,
        "truncated": isinstance(left_out, int) and left_out > 0,
        "files": [],
        **error_fields(entry),
    }


# --- the conversation ------------------------------------------------------------------------


def read_and_answer(
    purpose: str,
    captured: JsonObject,
    agent: AgentsRow,
    workspace: RepositoryWorkspace,
    *,
    system_prompt: str,
    call_completion: CompletionCall,
    settings: object,
    limits: ReadingLimits,
    trace: RunTrace,
) -> Outcome:
    """Let the model read until it answers, then check the answer like a single call's."""
    files = workspace.list_files()
    request = user_message(captured, budget_chars=limits.context_chars, repository_files=files.text)
    trace.add(
        "repository",
        "step",
        f"Asked {agent.name} to read what the {_document(purpose)} needs "
        f"({files.entries} files to choose from)",
    )
    reading = _Reading(
        purpose=purpose,
        agent=agent,
        workspace=workspace,
        system_prompt=system_prompt,
        call_completion=call_completion,
        settings=settings,
        limits=limits,
        trace=trace,
        messages=[{"role": "user", "content": request}],
        labels=context_labels(captured),
    )
    return reading.run()


@dataclass(slots=True)
class _Reading:
    """One run's conversation with the model and what it has used of the limits."""

    purpose: str
    agent: AgentsRow
    workspace: RepositoryWorkspace
    system_prompt: str
    call_completion: CompletionCall
    settings: object
    limits: ReadingLimits
    trace: RunTrace
    messages: list[ChatMessage]
    labels: tuple[str, ...] | None = None
    """The board's label names the run was given; a RoadMap names no other."""
    usage: dict[str, int] = field(default_factory=dict[str, int])
    model: str | None = None
    calls_made: int = 0
    repairs: int = 0
    final: bool = False
    insisted: int = 0
    set_aside: int = 0

    def run(self) -> Outcome:
        tools = workspace_tools()
        while not self.trace.cancelled:
            self._fit()
            completion = self.call_completion(
                self.settings,
                asdict(self.agent),
                system_prompt=self.system_prompt,
                messages=self.messages,
                # No response_format beside tools: a provider that constrains the answer to the
                # schema can no longer call a tool. The prompt shows the schema, and the repair
                # rounds hold the answer to it.
                response_schema=None,
                tools=tools,
                tool_choice="none" if self.final else "auto",
            )
            if not completion["ok"]:
                return self._failed(completion)
            self._count(completion)
            if completion["tool_calls"]:
                stopped = self._answer_calls(completion["text"], completion["tool_calls"])
            else:
                stopped = self._check(completion["text"])
            if stopped is not None:
                return stopped
        return Outcome(cancelled=True)

    def _count(self, completion: Completion) -> None:
        usage = completion.get("usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    self.usage[key] = self.usage.get(key, 0) + value
        model = completion.get("model")
        if isinstance(model, str):
            self.model = model

    def _failed(self, completion: Completion) -> Outcome:
        error = completion["error"] or ""
        if error.startswith(TOOLS_REFUSED) and self.calls_made == 0:
            # The connection test found tool calling, and the provider refuses it now (a model
            # swapped behind the endpoint): the run reads a fixed snapshot instead.
            return Outcome(error_code=TOOLS_REFUSED_CODE, error_message=error, retryable=True)
        note(self.trace, "writing", f"The provider call failed: {clip(error, 300)}", "error")
        return call_failed(completion)

    def _answer_calls(self, text: str, calls: Sequence[ToolCall]) -> Outcome | None:
        self.messages.append(assistant_message(text, calls))
        if text.strip() and not self.trace.add("repository", "note", text):
            return Outcome(cancelled=True)
        for call in calls:
            if self.final or self.calls_made >= self.limits.tool_steps:
                self.messages.append(tool_message(call, NO_MORE_CALLS))
                continue
            answer = _answer(self.workspace, call)
            self.calls_made += 1
            self.messages.append(tool_message(call, answer.text))
            recorded = self.trace.add(
                "repository",
                "tool",
                answer.summary,
                tool=call["name"],
                arguments=call["arguments"],
                answer=answer.trace(),
            )
            if not recorded:
                return Outcome(cancelled=True)
        if self.final:
            self.insisted += 1
            if self.insisted < 2:
                return None
            message = "The model kept calling tools after this run's tool calls were used up"
            note(self.trace, "writing", message, "error")
            return Outcome(error_code="invalid_output", error_message=message, retryable=True)
        if self.calls_made >= self.limits.tool_steps:
            self.final = True
            steps = self.limits.tool_steps
            self.trace.add(
                "repository",
                "limit",
                f"Reached the {steps} tool calls this run allows; "
                "asked the model for its answer now",
            )
            self.messages.append(
                {"role": "user", "content": STEP_LIMIT_REQUEST.format(steps=steps)}
            )
        return None

    def _check(self, text: str) -> Outcome | None:
        written = "a corrected answer" if self.repairs else "its answer"
        aside = (
            f"; {self.set_aside} older tool answers were set aside to fit its context"
            if self.set_aside
            else ""
        )
        calls = f"{self.calls_made} tool call{'' if self.calls_made == 1 else 's'}"
        self.trace.add(
            "writing",
            "step",
            f"The model wrote {written} after {calls} ({len(text)} characters){aside}",
        )
        try:
            payload = parse_output(self.purpose, text, labels=self.labels)
        except (ValueError, ValidationError, ValidationFailure) as exc:
            if self.repairs >= MAX_REPAIRS:
                note(self.trace, "checking", gave_up(exc), "error")
                return invalid_outcome(exc)
            self.repairs += 1
            self.trace.add("checking", "repair", repair_step(problem_of(exc)))
            self.messages.append(assistant_message(text, []))
            self.messages.append({"role": "user", "content": repair_request(problem_of(exc))})
            return None
        self.trace.add("checking", "step", "The answer follows the schema and the rules")
        return Outcome(payload=payload, usage=dict(self.usage) or None, model=self.model)

    def _fit(self) -> None:
        count = set_aside_oldest(self.messages, self.system_prompt, self.limits.context_chars)
        if count and not self.set_aside:
            self.trace.add(
                "repository",
                "limit",
                "Older tool answers were set aside to stay within the model's context window; "
                "it can read them again",
            )
        self.set_aside += count


def _answer(workspace: RepositoryWorkspace, call: ToolCall) -> ToolAnswer:
    error = call["arguments_error"]
    if error is not None:
        name = clip(call["name"], 60)
        return ToolAnswer(
            text=(
                f"Error: the arguments of {name} are not valid JSON ({clip(error, 200)}). "
                "Call it again with a JSON object."
            ),
            summary=f"Called {name} with arguments that were not JSON",
            error="invalid_arguments",
        )
    return workspace.answer(call["name"], call["arguments"])


def conversation_chars(system_prompt: str, messages: Sequence[ChatMessage]) -> int:
    """What the conversation takes of the model's context, in characters."""
    total = len(system_prompt)
    for message in messages:
        total += len(message["content"])
        if message["role"] == "assistant":
            total += sum(
                len(call["name"]) + len(call["arguments_text"])
                for call in message.get("tool_calls", [])
            )
    return total


def set_aside_oldest(messages: list[ChatMessage], system_prompt: str, budget_chars: int) -> int:
    """Replace the oldest tool answers by a one-line note until the conversation fits
    ``budget_chars``; answers how many were set aside. The model can call the tool again."""
    size = conversation_chars(system_prompt, messages)
    count = 0
    for index, message in enumerate(messages):
        if size <= budget_chars:
            break
        if message["role"] != "tool" or message["content"].startswith(SET_ASIDE_MARK):
            continue
        replacement = SET_ASIDE.format(chars=len(message["content"]))
        size -= len(message["content"]) - len(replacement)
        messages[index] = {
            "role": "tool",
            "tool_call_id": message["tool_call_id"],
            "content": replacement,
        }
        count += 1
    return count


def _document(purpose: str) -> str:
    return {"analysis": "analysis", "roadmap": "RoadMap"}.get(purpose, "QA instructions")
