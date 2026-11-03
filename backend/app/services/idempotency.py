"""Replaying a board write that carried an ``Idempotency-Key``.

A board keeps one record per actor and key: the request's fingerprint and the answer it got. A
retried request with the same fingerprint is answered from the record until it expires; the same
key with another fingerprint is refused. The rule runs on ``BoardIdempotencyRepository``, so it is
unit-tested on a fake; ``common.run_idempotent`` applies it for the services that still hold a
connection. A request's fingerprint is ``request_fingerprint`` of what it asks for.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TypeIs

from pydantic import JsonValue

from ..core.dates import iso_utc
from ..core.errors import Conflict
from ..db.generated.board import IdempotencyRecordsRow
from ..repositories.idempotency import BoardIdempotencyRepository

type JsonObject = dict[str, JsonValue]


def _is_object(value: JsonValue) -> TypeIs[JsonObject]:
    return isinstance(value, dict)


def request_fingerprint(payload: object) -> str:
    """SHA-256 of the payload's canonical JSON: keys sorted, no spaces, anything else as text."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stored_answer(
    records: BoardIdempotencyRepository,
    *,
    actor_id: str,
    key: str,
    fingerprint: str,
    now: datetime,
) -> JsonObject | None:
    """The answer stored for a replayed key, or None when the request must run.

    An expired record is removed, so the request runs and its answer replaces it. Every answer
    is stored as a JSON object; a record that holds anything else (only a hand-edited one can)
    counts as no answer, as a stored ``null`` always did.
    """
    existing = records.get(actor_id, key)
    if existing is None:
        return None
    if existing.request_hash != fingerprint:
        raise Conflict(
            "Idempotency key was already used with a different payload",
            code="idempotency_key_reused",
        )
    if existing.expires_at >= iso_utc(now):
        answer: JsonValue = json.loads(existing.response_json)
        return answer if _is_object(answer) else None
    records.delete(actor_id, key)
    return None


def remember(
    records: BoardIdempotencyRepository,
    *,
    actor_id: str,
    key: str,
    fingerprint: str,
    answer: Mapping[str, object],
    now: datetime,
    ttl_seconds: int,
) -> None:
    """Store the answer for ``ttl_seconds``, replacing a record held for the same actor and key."""
    records.put(
        IdempotencyRecordsRow(
            actor_id=actor_id,
            idempotency_key=key,
            request_hash=fingerprint,
            response_json=json.dumps(answer),
            created_at=iso_utc(now),
            expires_at=iso_utc(now + timedelta(seconds=ttl_seconds)),
        )
    )
