"""A generation run's record and the steps that execute it.

The answer a run gives over the API, and the steps ``LoopGenerationService._run`` takes: ask the
model (repairing an answer that does not validate), record the step a run is on, attach the
repository snapshot, promote the result, or record why there is none. Each step takes the unit
of work, the clock and the collaborators it needs as arguments; the service's private methods
(``_generate``, ``_phase``, ``_attach_repositories``, ``_promote``, ``_finish``) hand them over.

A run logs ``generation_run_started`` when it starts and ``generation_run_finished`` once when it
ends, whichever way; neither line carries a prompt, a message or the model's answer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue, ValidationError

from ..core.context import ActorContext
from ..core.errors import ApiError
from ..db.generated.board import LoopGenerationRunsRow
from ..db.generated.registry import AgentsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.loops import AnalysisPayload, PlanPayload, QaInstructions
from .idempotency import request_fingerprint
from .loop_documents import LoopDocumentService
from .loop_generation_prompts import (
    MAX_OUTPUT_CHARS,
    JsonObject,
    parse_output,
    response_schema_for,
    user_message,
)
from .loop_links import LoopWorkflowLinks
from .loops import ensure_writable, refresh_stage, require_loop
from .runtime import ResponseSchema

logger = logging.getLogger("tralala.loop_generation")

MAX_REPAIRS = 2
# A failed run keeps an error's details up to this many characters of JSON, and an unexpected
# exception's text up to MAX_EXCEPTION_TEXT.
MAX_ERROR_DETAILS_CHARS = 2000
MAX_EXCEPTION_TEXT = 500
# Keys an error's details never keep, at any depth: what the model was told and the credentials.
_HIDDEN_DETAIL_KEYS = frozenset(
    {"prompt", "system_prompt", "messages", "api_key", "token", "authorization", "password"}
)

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
    """``RepositorySnapshotService.for_board``: one entry per enabled repository on the board."""

    def for_board(self, board_id: str) -> Sequence[Mapping[str, JsonValue]]: ...


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
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class Failure:
    """Why a run failed, as ``finish`` records it."""

    error_code: str
    error_message: str
    error_details: JsonValue = None


@dataclass(frozen=True, slots=True)
class _Ended:
    """How ``promote`` left a run, for its finished line."""

    status: str
    error_code: str | None
    now: str
    usage_json: str = "{}"


def _without_secrets(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _without_secrets(item)
            for key, item in value.items()
            if key.lower() not in _HIDDEN_DETAIL_KEYS
        }
    if isinstance(value, list):
        return [_without_secrets(item) for item in value]
    return value


def error_details(details: Mapping[str, object] | None) -> JsonValue:
    """An error's details as a run keeps them: JSON without a key that names a prompt, the
    messages or a credential at any depth, at most ``MAX_ERROR_DETAILS_CHARS`` characters; a
    longer one is kept as its truncated text."""
    if not details:
        return None
    loaded: JsonValue = json.loads(json.dumps(dict(details), default=str))
    kept = _without_secrets(loaded)
    text = json.dumps(kept)
    return kept if len(text) <= MAX_ERROR_DETAILS_CHARS else text[:MAX_ERROR_DETAILS_CHARS]


def failure_of(exc: Exception) -> Failure:
    """An application error names itself (its code, message and details); anything else is its
    class name and the start of its text."""
    if isinstance(exc, ApiError):
        return Failure(exc.code or "generation_failed", exc.message, error_details(exc.details))
    name = type(exc).__name__
    text = str(exc)[:MAX_EXCEPTION_TEXT]
    return Failure("generation_failed", f"{name}: {text}" if text else name)


def snapshot_chars(captured: JsonValue) -> int:
    """The characters of repository file content a run's captured context holds."""
    context = captured.get("context") if isinstance(captured, dict) else None
    repositories = context.get("repositories") if isinstance(context, dict) else None
    if not isinstance(repositories, list):
        return 0
    total = 0
    for entry in repositories:
        files = entry.get("files") if isinstance(entry, dict) else None
        for item in files if isinstance(files, list) else []:
            content = item.get("content") if isinstance(item, dict) else None
            total += len(content) if isinstance(content, str) else 0
    return total


def _token_count(usage: JsonValue, name: str) -> int | None:
    value = usage.get(name) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _duration_ms(started_at: str | None, finished_at: str) -> int | None:
    if not started_at:
        return None
    try:
        elapsed = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return round(elapsed.total_seconds() * 1000)


def log_started(row: LoopGenerationRunsRow) -> None:
    logger.info(
        "generation_run_started",
        extra={"run_id": row.id, "purpose": row.purpose, "agent_id": row.agent_id},
    )


def _log_finished(row: LoopGenerationRunsRow, ended: _Ended, captured: JsonValue) -> None:
    usage: JsonValue = json.loads(ended.usage_json)
    logger.info(
        "generation_run_finished",
        extra={
            "run_id": row.id,
            "purpose": row.purpose,
            "agent_id": row.agent_id,
            "status": ended.status,
            "error_code": ended.error_code,
            "duration_ms": _duration_ms(row.started_at, ended.now),
            "prompt_tokens": _token_count(usage, "prompt_tokens"),
            "completion_tokens": _token_count(usage, "completion_tokens"),
            "snapshot_chars": snapshot_chars(captured),
        },
    )


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
                **({"error": item["error"]} if item.get("error") else {}),
            }
            for item in repositories
            if isinstance(item, dict)
        ]
    return sources


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


def generate(
    purpose: str,
    captured: JsonObject,
    agent: AgentsRow,
    *,
    system_prompt: str,
    call_completion: CompletionCall,
    settings: object,
) -> Outcome:
    messages = [{"role": "user", "content": user_message(captured)}]
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
        except (ValueError, ValidationError) as exc:
            if attempt >= MAX_REPAIRS:
                return Outcome(
                    error_code="invalid_output",
                    error_message="Generated output did not match the schema",
                    details=str(exc)[:2000],
                    retryable=False,
                )
            repair = {
                "role": "user",
                "content": (
                    "That response did not validate. Fix it and return the corrected JSON "
                    f"object only. Error: {str(exc)[:1500]}"
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
) -> JsonObject:
    """Fetch the board's repositories into the captured context and record what was seen.

    The context and the source revisions are written back to the run, so `input_json` holds the
    same snapshot the model received and `source_revisions_json` carries the commit and the file
    paths — never the file contents, which live only in the run's own input.
    """
    if snapshots is None:
        return captured
    entries = snapshots.for_board(board_id)
    source = captured.get("context")
    context: JsonObject = dict(source) if isinstance(source, dict) else {}
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
    _log_finished(row, ended, captured)


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
) -> _Ended:
    run_id = row.id
    if row.status == "cancelled":
        return _Ended("cancelled", None, timestamp())
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
            output_json=json.dumps({"stale_candidate": payload})[:MAX_OUTPUT_CHARS],
            now=now,
        )
        return _Ended("failed", "generation_input_changed", now)
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
        output_json=json.dumps({**payload, "_references": outputs})[:MAX_OUTPUT_CHARS],
        usage_json=usage_json,
        model=result.model or row.model,
        now=now,
    )
    refresh_stage(repos, loop_id, now=now)
    return _Ended("completed", None, now, usage_json)


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
        _log_finished(row, _Ended(status, error_code, now), _loads(row.input_json))
