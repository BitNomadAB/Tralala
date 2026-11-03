from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection

from ..core.context import ActorContext
from ..db.generated.board import ActivityLogRow
from ..repositories.sql.activity import SqlActivityRepository
from ..storage.sqlite import utcnow


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
    changes: dict[str, Any] | None = None,
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


def serialize_activity(row: dict[str, Any]) -> dict[str, Any]:
    entry = dict(row)
    raw = entry.pop("changes_json", "{}")
    try:
        entry["changes"] = json.loads(raw)
    except (TypeError, ValueError):
        entry["changes"] = {}
    return entry
