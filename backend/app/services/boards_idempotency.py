"""Replaying a board creation: an idempotency key answers a retry with the board it made.

The key is reserved before the board exists, so a retry that arrives while the first request is
still creating it is told so instead of creating a second board; the stored answer expires after
``idempotency_ttl_seconds``. ``BoardService.create`` (``services.boards``) calls these with its
registry unit of work, settings and clock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict
from ..db.generated.registry import BoardsRow, IdempotencyRecordsRow
from ..repositories.registry import RegistryUnitOfWork
from .boards_registry import BoardEntry, JsonObject, json_object


def replay_or_reserve(
    store: RegistryUnitOfWork,
    settings: Settings,
    actor: ActorContext,
    key: str,
    fingerprint: str,
    board_id: str,
    *,
    clock: Callable[[], datetime],
    serialize: Callable[[BoardsRow], BoardEntry],
) -> BoardEntry | JsonObject | None:
    """The answer a replayed key gets, or None after reserving the key for ``board_id``.

    The key is reserved before the board exists, so a retry that arrives while the first
    request is still creating it is told so instead of creating a second board.
    """
    with store.writer() as repos:
        existing = repos.idempotency.get(actor.actor_id, key)
        if existing is None:
            pending = {"_pending": True, "board_id": board_id}
            repos.idempotency.put(_record(settings, actor, key, fingerprint, pending, clock=clock))
            return None
        if existing.request_hash != fingerprint:
            raise Conflict(
                "Idempotency key was already used with a different payload",
                code="idempotency_key_reused",
            )
        stored = json_object(json.loads(existing.response_json), "a stored response")
        if not stored.get("_pending"):
            return stored
        pending_id = str(stored.get("board_id") or "")
        row = repos.boards.get(pending_id) if pending_id else None
    if row is not None and row.status == "active":
        return serialize(row)
    if row is not None and row.status == "error":
        raise Conflict(
            "Board creation with this idempotency key failed; inspect the "
            "board entry before retrying",
            code="creation_failed",
            details={"board_id": pending_id},
        )
    raise Conflict(
        "Board creation is still in progress for this idempotency key",
        code="creation_in_progress",
        details={"board_id": pending_id},
    )


def _record(
    settings: Settings,
    actor: ActorContext,
    key: str,
    fingerprint: str,
    response: Mapping[str, object],
    *,
    clock: Callable[[], datetime],
) -> IdempotencyRecordsRow:
    moment = clock()
    expires = moment + timedelta(seconds=settings.idempotency_ttl_seconds)
    return IdempotencyRecordsRow(
        actor_id=actor.actor_id,
        idempotency_key=key,
        request_hash=fingerprint,
        response_json=json.dumps(response),
        created_at=iso_utc(moment),
        expires_at=iso_utc(expires),
    )


def remember(
    store: RegistryUnitOfWork,
    settings: Settings,
    actor: ActorContext,
    key: str | None,
    fingerprint: str,
    response: Mapping[str, object],
    *,
    clock: Callable[[], datetime],
) -> None:
    if not key:
        return
    with store.writer() as repos:
        repos.idempotency.put(_record(settings, actor, key, fingerprint, response, clock=clock))
