"""A generation run's record and the steps that execute it.

The answer a run gives over the API, and the steps ``LoopGenerationService._run`` takes: ask the
model (repairing an answer that does not validate), record the step a run is on, attach the
repository snapshot, promote the result, or record why there is none. Each step takes the unit
of work, the clock and the collaborators it needs as arguments; the service's private methods
(``_generate``, ``_phase``, ``_attach_repositories``, ``_promote``, ``_finish``) hand them over.

What a run reports about itself (its failure and its two log lines) is ``loop_generation_report``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from pydantic import JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..db.generated.board import LoopGenerationRunsRow
from ..db.generated.registry import AgentsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.loops import AnalysisPayload, PlanPayload, QaInstructions
from .idempotency import request_fingerprint
from .loop_documents import LoopDocumentService
from .loop_generation_prompts import (
    MAX_OUTPUT_CHARS,
    MIN_SNAPSHOT_CHARS,
    REPOSITORY_OVERHEAD_CHARS,
    JsonObject,
    context_size,
    parse_output,
    response_schema_for,
    user_message,
    without_drafts,
)
from .loop_generation_report import Ended, error_details, log_finished
from .loop_links import LoopWorkflowLinks
from .loops import ensure_writable, refresh_stage, require_loop
from .runtime import ResponseSchema

logger = logging.getLogger("tralala.loop_generation")

MAX_REPAIRS = 2
type RunEntry = dict[str, object]

# A run's answer leaves these out: the captured input and role stay in the run's own record, and
# the JSON columns are answered parsed under names without ``_json``.
_RUN_HIDDEN = (
    "output_json",
    "source_revisions_json",
    "usage_json",
    "input_json",
    "role_snapshot_json",
    "created_by_actor_id",
    "created_by_actor_type",
)


class RepositorySnapshots(Protocol):
    """``RepositorySnapshotService.for_board``: one entry per enabled repository on the board, the
    file content of all of them together at most ``budget_chars`` characters of context."""

    def for_board(
        self, board_id: str, *, budget_chars: int
    ) -> Sequence[Mapping[str, JsonValue]]: ...


class CompletionCall(Protocol):
    """``runtime.call_completion`` as a generation calls it: the discussions' ``AgentCall`` plus the
    schema the answer must follow, which the runtime sends only where the agent's provider takes
    one (``agents.supports_json_schema``)."""

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        response_schema: ResponseSchema | None,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the model returned: a validated payload, or why there is none."""

    payload: JsonObject | None = None
    usage: object = None
    model: str | None = None
    error_code: str = ""
    error_message: str = ""
    details: str | None = None
    error_details: JsonValue = None
    retryable: bool = False


def stored_output(value: Mapping[str, object]) -> str:
    """A run's output as stored: whole JSON of at most ``MAX_OUTPUT_CHARS`` characters, text kept as
    written (an escaped "å" is six characters, "å" one). Output that still does not fit is
    replaced by a note, never cut, because cut JSON makes the run unreadable."""
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return json.dumps({"output_omitted": True, "chars": len(text)})


def _loads(raw: str) -> JsonValue:
    value: JsonValue = json.loads(raw or "{}")
    return value


def _public_sources(sources: JsonValue) -> JsonValue:
    """A repository entry names what the analysis was based on; the file paths stay in the run's
    own record and the contents are never part of an API response."""
    if not isinstance(sources, dict):
        return sources
    repositories = sources.get("repositories")
    if isinstance(repositories, list):
        sources["repositories"] = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "branch": item.get("branch"),
                "commit_sha": item.get("commit_sha"),
                "file_count": item.get("file_count", 0),
                "truncated": bool(item.get("truncated")),
                **_budget_fields(item),
                **({"error": item["error"]} if item.get("error") else {}),
            }
            for item in repositories
            if isinstance(item, dict)
        ]
    return sources


def _budget_fields(entry: Mapping[str, JsonValue]) -> JsonObject:
    """What a repository was allowed and what it used of the context budget, when it had one."""
    if "budget_chars" not in entry:
        return {}
    return {
        "budget_chars": entry.get("budget_chars"),
        "snapshot_chars_included": entry.get("snapshot_chars_included", 0),
        "content_omitted": bool(entry.get("content_omitted")),
    }


def serialize_run(row: LoopGenerationRunsRow) -> RunEntry:
    entry: RunEntry = {
        name: value for name, value in asdict(row).items() if name not in _RUN_HIDDEN
    }
    entry["output"] = _loads(row.output_json)
    entry["source_revisions"] = _public_sources(_loads(row.source_revisions_json))
    entry["usage"] = _loads(row.usage_json)
    return entry


def _paths(files: JsonValue) -> list[JsonValue]:
    if not isinstance(files, list):
        return []
    return [item["path"] for item in files if isinstance(item, dict)]


def _answer_text(outcome: Mapping[str, object]) -> str:
    text = outcome["text"]
    if not isinstance(text, str):
        raise TypeError("The provider answer carries no text")
    return text


def _call_failed(outcome: Mapping[str, object]) -> Outcome:
    return Outcome(
        error_code="provider_error",
        error_message=f"The provider call failed: {outcome['error']}",
        retryable=True,
    )


def _system_actor(run_row: LoopGenerationRunsRow) -> ActorContext:
    return ActorContext(
        actor_id=run_row.agent_id or "generation",
        actor_type="agent",
        actor_name=run_row.agent_name or "Generation agent",
    )


def _problem(exc: Exception) -> str:
    """What a repair message and a failed run say about an answer that did not validate: a rule's
    message with its details (the Phase and the reference that is missing), or the parser's text."""
    if isinstance(exc, ValidationFailure):
        details = f" {json.dumps(dict(exc.details), default=str)}" if exc.details else ""
        return f"{exc.message}{details}"
    return str(exc)


def _invalid(exc: Exception) -> Outcome:
    if isinstance(exc, ValidationFailure):
        return Outcome(
            error_code="invalid_output",
            error_message=f"Generated output broke a rule: {exc.message}",
            error_details=error_details({"rule": exc.code, **(exc.details or {})}),
            retryable=False,
        )
    return Outcome(
        error_code="invalid_output",
        error_message="Generated output did not match the schema",
        details=_problem(exc)[:2000],
        retryable=False,
    )


def generate(
    purpose: str,
    captured: JsonObject,
    agent: AgentsRow,
    *,
    system_prompt: str,
    call_completion: CompletionCall,
    settings: object,
    context_chars: int,
) -> Outcome:
    messages = [{"role": "user", "content": user_message(captured, budget_chars=context_chars)}]
    # The same schema the prompt shows; the runtime sends it only to a provider that takes one.
    response_schema = response_schema_for(purpose)
    outcome = call_completion(
        settings,
        asdict(agent),
        system_prompt=system_prompt,
        messages=messages,
        response_schema=response_schema,
    )
    if not outcome["ok"]:
        return _call_failed(outcome)
    usage = outcome.get("usage")
    model = outcome.get("model")
    model_name = model if isinstance(model, str) else None
    text = _answer_text(outcome)
    for attempt in range(MAX_REPAIRS + 1):
        try:
            payload = parse_output(purpose, text)
            return Outcome(payload=payload, usage=usage, model=model_name)
        except (ValueError, ValidationError, ValidationFailure) as exc:
            if attempt >= MAX_REPAIRS:
                return _invalid(exc)
            repair = {
                "role": "user",
                "content": (
                    "That response did not validate. Fix it and return the corrected JSON "
                    f"object only. Error: {_problem(exc)[:1500]}"
                ),
            }
            outcome = call_completion(
                settings,
                asdict(agent),
                system_prompt=system_prompt,
                messages=[*messages, {"role": "assistant", "content": text}, repair],
                response_schema=response_schema,
            )
            if not outcome["ok"]:
                return _call_failed(outcome)
            text = _answer_text(outcome)
    return Outcome(
        error_code="invalid_output",
        error_message="Generated output did not match the schema",
        retryable=False,
    )


def record_phase(board_id: str, run_id: str, phase: str, *, store: BoardUnitOfWork) -> None:
    """Record which step a run is on, so a watcher sees progress and a failure names its step.

    A run must never fail because its progress could not be written down, so this is best
    effort: the phase is decoration around the real work.
    """
    try:
        with store.writer(board_id) as repos:
            repos.generation_runs.set_phase(run_id, phase)
    except Exception:  # noqa: BLE001 - progress reporting never breaks a run
        logger.warning("could not record generation phase", extra={"run_id": run_id})


def attach_repositories(
    board_id: str,
    loop_id: str,
    run_id: str,
    captured: JsonObject,
    *,
    store: BoardUnitOfWork,
    snapshots: RepositorySnapshots | None,
    budget_chars: int,
) -> JsonObject:
    """Fetch the board's repositories into the captured context and record what was seen.

    The documents come first; the repositories get what remains of ``budget_chars``, cut to fit.
    When that is under ``MIN_SNAPSHOT_CHARS`` the previous AI drafts go without content, but only
    if the repositories then used the room; the Info always stays. The context and the source
    revisions are written back to the run, so `input_json` holds the same snapshot the model
    received and `source_revisions_json` carries the commit, the file paths and the budget — never
    the file contents, which live only in the run's own input.
    """
    if snapshots is None:
        return captured
    source = captured.get("context")
    context: JsonObject = dict(source) if isinstance(source, dict) else {}
    room = budget_chars - context_size(context) - REPOSITORY_OVERHEAD_CHARS
    slim = context
    if room < MIN_SNAPSHOT_CHARS:
        slim = without_drafts(context, str(captured.get("purpose")))
        room = budget_chars - context_size(slim) - REPOSITORY_OVERHEAD_CHARS
    entries = snapshots.for_board(board_id, budget_chars=max(room, 0))
    used = sum(_included(entry) for entry in entries)
    if used <= budget_chars - context_size(context) - REPOSITORY_OVERHEAD_CHARS:
        slim = context  # the drafts fit beside what the repositories used
    context = slim
    repositories: list[JsonValue] = [dict(entry) for entry in entries]
    context["repositories"] = repositories or "no enabled repository is linked to this board"
    captured = {**captured, "context": context}
    described: list[JsonValue] = [
        {
            "id": entry["id"],
            "name": entry["name"],
            "branch": entry.get("branch"),
            "commit_sha": entry.get("commit_sha"),
            "file_count": entry.get("file_count", 0),
            "truncated": bool(entry.get("truncated")),
            **_budget_fields(entry),
            "files": _paths(entry.get("files", [])),
            **({"error": entry["error"]} if entry.get("error") else {}),
        }
        for entry in entries
    ]
    known = captured.get("source_revisions")
    sources: JsonObject = dict(known) if isinstance(known, dict) else {}
    sources["repositories"] = described
    captured["source_revisions"] = sources
    # `context_hash` stays the fingerprint of the *documents*, because that is what the promote
    # step compares to detect a changed input. The snapshot gets its own hash, which becomes the
    # run's `input_hash`: two runs over different commits are then visibly different inputs.
    snapshot_hash = request_fingerprint(captured["context"])
    with store.writer(board_id) as repos:
        repos.generation_runs.set_input(
            loop_id,
            run_id,
            input_json=json.dumps(captured),
            input_hash=snapshot_hash,
            source_revisions_json=json.dumps(sources),
        )
    return captured


def _included(entry: Mapping[str, JsonValue]) -> int:
    value = entry.get("snapshot_chars_included")
    return value if isinstance(value, int) else 0


def promote(
    board_id: str,
    loop_id: str,
    run_id: str,
    captured: JsonObject,
    payload: JsonObject,
    result: Outcome,
    *,
    store: BoardUnitOfWork,
    documents: LoopDocumentService,
    links: LoopWorkflowLinks,
    timestamp: Callable[[], str],
) -> None:
    with store.writer(board_id) as repos:
        row = repos.generation_runs.get(run_id)
        if row is None:
            return
        ended = _promote_run(
            repos,
            row,
            loop_id,
            captured,
            payload,
            result,
            documents=documents,
            links=links,
            timestamp=timestamp,
        )
    log_finished(row, ended, captured)


def _promote_run(
    repos: BoardRepositories,
    row: LoopGenerationRunsRow,
    loop_id: str,
    captured: JsonObject,
    payload: JsonObject,
    result: Outcome,
    *,
    documents: LoopDocumentService,
    links: LoopWorkflowLinks,
    timestamp: Callable[[], str],
) -> Ended:
    run_id = row.id
    if row.status == "cancelled":
        return Ended("cancelled", None, timestamp())
    loop = require_loop(repos, loop_id)
    ensure_writable(loop)
    current = documents.collect_context(repos, loop)
    if request_fingerprint(current) != captured["context_hash"]:
        now = timestamp()
        repos.generation_runs.fail_input_changed(
            run_id,
            message=(
                "The documents changed while the model was working; the result was "
                "kept for inspection and was not promoted"
            ),
            output_json=stored_output({"stale_candidate": payload}),
            now=now,
        )
        return Ended("failed", "generation_input_changed", now)
    provenance = {
        "generation_run_id": run_id,
        "agent_id": row.agent_id,
        "agent_name": row.agent_name,
        "model": result.model or row.model,
    }
    outputs: object
    if captured["purpose"] == "analysis":
        outputs = documents.store_generated_analysis(
            repos,
            loop,
            AnalysisPayload.model_validate(payload),
            _system_actor(row),
            run_id=run_id,
            provenance=provenance,
        )
    elif captured["purpose"] == "roadmap":
        outputs = documents.store_generated_roadmap(
            repos,
            loop,
            PlanPayload.model_validate(payload),
            _system_actor(row),
            run_id=run_id,
            provenance=provenance,
        )
    else:
        outputs = links.apply_qa_instructions(
            repos,
            loop,
            QaInstructions.model_validate(payload),
            run_id=run_id,
            provenance=provenance,
        )
    now = timestamp()
    usage_json = json.dumps(result.usage or {})
    repos.generation_runs.complete(
        run_id,
        output_json=stored_output({**payload, "_references": outputs}),
        usage_json=usage_json,
        model=result.model or row.model,
        now=now,
    )
    refresh_stage(repos, loop_id, now=now)
    return Ended("completed", None, now, usage_json)


def finish(
    board_id: str,
    loop_id: str,
    run_id: str,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    details: str | None = None,
    error_details: JsonValue = None,
    retryable: bool = False,
    store: BoardUnitOfWork,
    timestamp: Callable[[], str],
) -> None:
    """End a run without a result. ``details`` is appended to the message; ``error_details``
    (already passed through ``error_details()``) becomes the run's output."""
    del loop_id
    output: JsonObject = {} if error_details is None else {"error_details": error_details}
    try:
        with store.writer(board_id) as repos:
            row = repos.generation_runs.get(run_id)
            now = timestamp()
            repos.generation_runs.finish(
                run_id,
                status=status,
                error_code=error_code,
                error_message=(
                    (error_message or "")
                    + (f" ({details})" if details else "")
                    + ("" if retryable else " (not retryable)")
                ).strip()
                or None,
                output_json=json.dumps(output),
                now=now,
            )
    except Exception:  # never mask the original failure
        logger.exception("could not record generation failure", extra={"run_id": run_id})
        return
    if row is not None:
        log_finished(row, Ended(status, error_code, now), _loads(row.input_json))
