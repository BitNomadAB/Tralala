"""A generation run's process tree: the steps a person reads to learn how an answer was made.

The run panel is not a fixed list of three phases. A run whose model reads the repositories through
tools takes as many steps as the model needs, an answer that breaks a rule is sent back, and a limit
can end the reading early. Someone watching the run, or reading it afterwards, only learns how the
analysis was made when each of those is a line in plain words, so ``RunTrace`` keeps one step per
event and writes the whole list to the run after every one (``trace_json``, best effort like the
phase): the panel grows while the run works, and the tree stays on the run.

A step never holds a file's content or the model's answer: a stage, a kind, one sentence, the time,
and for a tool call its name, its arguments and what the answer held (``ToolAnswer.trace``). The
model's own words beside a tool call ("I'll read the installation guide first") are a ``note``:
they are what the model said it was doing, bounded like every other text here.

The stages, in order, each appearing when the run reaches it: ``documents`` (the Loop's documents),
``repository`` (the code), ``writing`` (the model's answer), ``checking`` (the schema and the rules,
with every repair round) and ``saving`` (the draft, or why it was not saved).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Final, Literal, NotRequired, Protocol, TypedDict

from pydantic import JsonValue

from .repository_problems import error_fields

type Stage = Literal["documents", "repository", "writing", "checking", "saving"]
type StepKind = Literal["step", "tool", "note", "repair", "limit", "error"]

STAGES: Final[tuple[Stage, ...]] = ("documents", "repository", "writing", "checking", "saving")
# A run records at most this many steps; the defaults (60 tool calls, two repairs) stay far below.
MAX_STEPS: Final = 1_000
TEXT_CHARS: Final = 500
NOTE_CHARS: Final = 1_000
ARGUMENT_CHARS: Final = 200
# How a person reads a document kind in a step.
DOCUMENT_NAMES: Final = {
    "info": "Info",
    "analysis_ai": "analysis draft",
    "analysis": "approved analysis",
    "roadmap_ai": "RoadMap draft",
    "roadmap": "approved RoadMap",
}


class TraceStep(TypedDict):
    stage: Stage
    kind: StepKind
    text: str
    at: str
    tool: NotRequired[str]
    arguments: NotRequired[dict[str, JsonValue]]
    answer: NotRequired[dict[str, JsonValue]]
    # A repair round of a face for people that broke its template: how many problems it had.
    face: NotRequired[int]


class TraceCounts(TypedDict):
    """What the steps add up to: tool calls, distinct files read, searches, listings, repairs, and
    the repairs that were about the face for people."""

    tool_calls: int
    files_read: int
    searches: int
    listings: int
    repairs: int
    face_repairs: int


class TraceWriter(Protocol):
    """Writes the steps so far to the run and answers the run's status after the write (None when
    it could not tell)."""

    def __call__(self, trace_json: str, /) -> str | None: ...


def clip(value: str, limit: int) -> str:
    """``value`` on one line, at most ``limit`` characters."""
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _arguments(arguments: JsonValue) -> dict[str, JsonValue]:
    """A tool call's arguments as the trace keeps them: an object's scalar values, text cut
    short."""
    if not isinstance(arguments, dict):
        return {}
    kept: dict[str, JsonValue] = {}
    for key, value in list(arguments.items())[:10]:
        if isinstance(value, str):
            kept[clip(key, 40)] = clip(value, ARGUMENT_CHARS)
        elif isinstance(value, bool | int | float) or value is None:
            kept[clip(key, 40)] = value
    return kept


class RunTrace:
    """The steps of one run, written to the run after every step."""

    def __init__(self, write: TraceWriter | None, clock: Callable[[], str]) -> None:
        self._write = write
        self._clock = clock
        self.steps: list[TraceStep] = []
        self.cancelled = False

    def add(
        self,
        stage: Stage,
        kind: StepKind,
        text: str,
        *,
        tool: str | None = None,
        arguments: JsonValue = None,
        answer: Mapping[str, JsonValue] | None = None,
        face: int | None = None,
    ) -> bool:
        """Record one step and write the trace; False once the run has been cancelled. ``face``
        is the number of face problems a repair round had."""
        if len(self.steps) < MAX_STEPS:
            step: TraceStep = {
                "stage": stage,
                "kind": kind,
                "text": clip(text, NOTE_CHARS if kind == "note" else TEXT_CHARS),
                "at": self._clock(),
            }
            if tool is not None:
                step["tool"] = clip(tool, 60)
                step["arguments"] = _arguments(arguments)
            if answer is not None:
                step["answer"] = dict(answer)
            if face is not None:
                step["face"] = face
            self.steps.append(step)
        if self._write is not None and self._write(self.dumps()) == "cancelled":
            self.cancelled = True
        return not self.cancelled

    def dumps(self) -> str:
        return json.dumps(self.steps, ensure_ascii=False)

    def counts(self) -> TraceCounts:
        return counts_of(parse_steps(self.dumps()))


def note(trace: RunTrace | None, stage: Stage, text: str, kind: StepKind = "step") -> None:
    """Add a step when the run keeps a trace; a run without one records nothing."""
    if trace is not None:
        trace.add(stage, kind, text)


def counts_of(steps: Sequence[JsonValue]) -> TraceCounts:
    """What a trace adds up to, for the run's log line and its based-on line."""
    files: set[str] = set()
    counted: TraceCounts = {
        "tool_calls": 0,
        "files_read": 0,
        "searches": 0,
        "listings": 0,
        "repairs": 0,
        "face_repairs": 0,
    }
    for step in steps:
        if not isinstance(step, dict):
            continue
        kind = step.get("kind")
        if kind == "repair":
            counted["repairs"] += 1
            face = step.get("face")
            counted["face_repairs"] += isinstance(face, int) and face > 0
        if kind != "tool":
            continue
        counted["tool_calls"] += 1
        tool = step.get("tool")
        counted["searches"] += tool == "search"
        counted["listings"] += tool == "list_files"
        answer = step.get("answer")
        read = answer.get("files_read") if isinstance(answer, dict) else None
        if tool == "read_file" and isinstance(read, list):
            files.update(item for item in read if isinstance(item, str))
    counted["files_read"] = len(files)
    return counted


def parse_steps(trace_json: str) -> list[JsonValue]:
    """A run's stored trace; a run recorded before the trace existed has none."""
    try:
        value: JsonValue = json.loads(trace_json or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


# --- the sentences ---------------------------------------------------------------------------


def documents_step(context: Mapping[str, JsonValue]) -> str:
    """Which of the Loop's documents the run read, by name and revision, and its plan's size."""
    documents = context.get("documents")
    named: list[str] = []
    if isinstance(documents, dict):
        for kind, label in DOCUMENT_NAMES.items():
            document = documents.get(kind)
            if isinstance(document, dict):
                named.append(f"the {label} (revision {document.get('revision_number')})")
    plan = context.get("plan")
    phases = plan.get("phases") if isinstance(plan, dict) else None
    if isinstance(phases, list) and phases:
        tickets = 0
        for phase in phases:
            listed = phase.get("tickets") if isinstance(phase, dict) else None
            tickets += len(listed) if isinstance(listed, list) else 0
        named.append(f"the plan ({_count(len(phases), 'Phase')}, {_count(tickets, 'Ticket')})")
    if not named:
        return "Read the Loop's goal; it has no documents yet"
    return "Read the Loop's " + _join(named).removeprefix("the ")


def snapshot_step(entry: Mapping[str, JsonValue], reason: str) -> str:
    """What the fixed snapshot of one repository sent, and why the run sent one."""
    if entry.get("error"):
        return repository_unreadable(entry)
    name = f"{entry.get('name')}{_at(entry)}"
    sent = entry.get("file_count")
    manifest = entry.get("manifest")
    listed = len(manifest) if isinstance(manifest, list) else 0
    omitted = entry.get("manifest_omitted")
    total = listed + (omitted if isinstance(omitted, int) else 0)
    return (
        f"Sent a fixed selection of {name}: {sent} of {_count(total, 'file')}, the rest by name "
        f"only ({reason})"
    )


def repository_unreadable(entry: Mapping[str, JsonValue]) -> str:
    """A repository the run could not read, in the words of ``repository_problems``: what went
    wrong and what to do (an ``error`` step, so the stage never shows as done)."""
    sha = entry.get("commit_sha")
    at = f" (commit {sha[:8]})" if isinstance(sha, str) and sha else ""
    return f"{error_fields(entry).get('problem', 'Could not read the repository')}{at}"


def unread_summary(entries: Sequence[JsonValue]) -> tuple[StepKind, str] | None:
    """After the repositories: a step when one or all of them could not be read, so the stage says
    what the run goes on without. None when every repository was read, or none is linked."""
    named = [entry for entry in entries if isinstance(entry, dict)]
    unread = [str(entry.get("name")) for entry in named if entry.get("error")]
    if not unread:
        return None
    if len(unread) == len(named):
        return (
            "error",
            "No code was read: the run goes on from the Loop's documents alone, and an analysis "
            "says so. Fix what the step above names, then run it again to base it on the code",
        )
    return "limit", f"Not read: {_join(unread)}; the run goes on with the rest of the code"


def workspace_step(name: str, commit_sha: str, files: int, text_bytes: int, left_out: int) -> str:
    """One repository opened for the model to read."""
    left = f"; {_count(left_out, 'file')} too large to read" if left_out else ""
    return (
        f"Opened {name} @ {commit_sha[:8]} for the model to read: {_count(files, 'file')}, "
        f"{_size(text_bytes)} of text{left}"
    )


def _at(entry: Mapping[str, JsonValue]) -> str:
    sha = entry.get("commit_sha")
    return f" @ {sha[:8]}" if isinstance(sha, str) and sha else ""


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _size(number: int) -> str:
    if number >= 1024 * 1024:
        return f"{number / (1024 * 1024):.1f} MB"
    if number >= 1024:
        return f"{number // 1024} KB"
    return f"{number} bytes"


def _join(parts: Sequence[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
