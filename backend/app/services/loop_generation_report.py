"""What a generation run reports about itself: why it failed, and its two log lines.

A failed run keeps an application error's code, message and details, the details without anything
that names a prompt, the messages or a credential and bounded in size, and any other exception as
its class name and the start of its text. Every run logs ``generation_run_started`` when it starts
and one ``generation_run_finished`` when it ends, whichever way, with its status, error code,
duration, token counts, the repository text it carried, the tool calls it made and its repair
rounds; neither line holds a prompt, a message or the model's answer. A run that needed a repair
says how many in its process tree (``repairs_line``), the face's rounds counted apart, so a model
that keeps failing the template is visible.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from ..core.errors import ApiError
from ..db.generated.board import LoopGenerationRunsRow
from .loop_generation_trace import TraceCounts, counts_of, parse_steps

logger = logging.getLogger("tralala.loop_generation")

# A failed run keeps an error's details up to this many characters of JSON, and an unexpected
# exception's text up to MAX_EXCEPTION_TEXT.
MAX_ERROR_DETAILS_CHARS = 2000
MAX_EXCEPTION_TEXT = 500
# Keys an error's details never keep, at any depth: what the model was told and the credentials.
_HIDDEN_DETAIL_KEYS = frozenset(
    {"prompt", "system_prompt", "messages", "api_key", "token", "authorization", "password"}
)


@dataclass(frozen=True, slots=True)
class Failure:
    """Why a run failed, as ``finish`` records it."""

    error_code: str
    error_message: str
    error_details: JsonValue = None


@dataclass(frozen=True, slots=True)
class Ended:
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


def repairs_line(counts: TraceCounts) -> str:
    """``Repairs: 2 (face: 2)``: the run's repair rounds, and how many of them were about the face
    for people; a run whose brief broke its sign adds those rounds (``Repairs: 1 (face: 0, brief:
    1)``)."""
    brief = f", brief: {counts['brief_repairs']}" if counts["brief_repairs"] else ""
    return f"Repairs: {counts['repairs']} (face: {counts['face_repairs']}{brief})"


def log_started(row: LoopGenerationRunsRow) -> None:
    logger.info(
        "generation_run_started",
        extra={"run_id": row.id, "purpose": row.purpose, "agent_id": row.agent_id},
    )


def log_finished(row: LoopGenerationRunsRow, ended: Ended, captured: JsonValue) -> None:
    usage: JsonValue = json.loads(ended.usage_json)
    counted = counts_of(parse_steps(row.trace_json))
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
            # What a model that reads through tools did: its tool calls and the files it read.
            "tool_calls": counted["tool_calls"],
            "files_read": counted["files_read"],
            "repairs": counted["repairs"],
            "face_repairs": counted["face_repairs"],
            "brief_repairs": counted["brief_repairs"],
        },
    )
