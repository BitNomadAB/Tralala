"""The board's activity log: the entry every write adds, and the feed that reads them back.

The feed reaches the board database only through the board unit of work (``app/repositories``);
``log_activity`` is the same entry for services that still hold a connection until their
conversion.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, TypedDict
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy.engine import Connection

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..db.generated.board import ActivityLogRow
from ..repositories.activity import ActivityQuery
from ..repositories.board import BoardUnitOfWork
from ..repositories.sql.activity import SqlActivityRepository


class ActivityEntry(TypedDict):
    """An activity log entry as the feed returns it: the row with its changes parsed."""

    id: str
    actor_id: str
    actor_type: str
    action: str
    entity_type: str
    entity_id: str
    request_id: str | None
    timestamp: str
    changes: JsonValue


class ActivityBoards(Protocol):
    """What the feed needs from BoardService: the board is registered, and its database."""

    def require_row(self, board_id: str) -> object: ...

    @property
    def boards(self) -> BoardUnitOfWork: ...


def activity_entry(
    actor: ActorContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    changes: Mapping[str, object] | None,
    entry_id: str,
    timestamp: str,
) -> ActivityLogRow:
    """One activity log row: who did what to which entity, and what changed."""
    return ActivityLogRow(
        id=entry_id,
        actor_id=actor.actor_id,
        actor_type=actor.actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=actor.request_id or None,
        timestamp=timestamp,
        changes_json=json.dumps(changes or {}),
    )


def log_activity(
    conn: Connection,
    actor: ActorContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    changes: Mapping[str, object] | None = None,
) -> str:
    """The same row for services that still hold a Connection (until GCS-T00g converts them)."""
    entry = activity_entry(
        actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        entry_id=str(uuid4()),
        timestamp=utcnow(),
    )
    SqlActivityRepository(conn).add(entry)
    return entry.id


def _changes(raw: str) -> JsonValue:
    """The stored changes; text that is not JSON reads as no changes."""
    try:
        value: JsonValue = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value


def feed_entry(row: ActivityLogRow) -> ActivityEntry:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_type": row.actor_type,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "request_id": row.request_id,
        "timestamp": row.timestamp,
        "changes": _changes(row.changes_json),
    }


def activity_feed(
    board_id: str,
    board_service: ActivityBoards,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ActivityEntry], int]:
    """A board's activity, newest first, and how many entries match in all."""
    board_service.require_row(board_id)
    query: ActivityQuery = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    if actor_type:
        query["actor_type"] = actor_type
    if action:
        query["action"] = action
    with board_service.boards.reader(board_id) as repos:
        total = repos.activity.count(query)
        rows = repos.activity.page(query, limit=limit, offset=offset)
    return [feed_entry(row) for row in rows], total
