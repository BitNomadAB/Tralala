from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..core.context import ActorContext
from ..storage.sqlite import utcnow


def log_activity(
    conn: Connection,
    actor: ActorContext,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    changes: dict[str, Any] | None = None,
) -> str:
    activity_id = str(uuid4())
    conn.execute(
        text(
            "INSERT INTO activity_log"
            " (id, actor_id, actor_type, action, entity_type, entity_id, request_id, timestamp,"
            "  changes_json)"
            " VALUES (:id, :actor_id, :actor_type, :action, :entity_type, :entity_id,"
            "         :request_id, :timestamp, :changes)"
        ),
        {
            "id": activity_id,
            "actor_id": actor.actor_id,
            "actor_type": actor.actor_type,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "request_id": actor.request_id or None,
            "timestamp": utcnow(),
            "changes": json.dumps(changes or {}),
        },
    )
    return activity_id


def serialize_activity(row: dict[str, Any]) -> dict[str, Any]:
    entry = dict(row)
    raw = entry.pop("changes_json", "{}")
    try:
        entry["changes"] = json.loads(raw)
    except (TypeError, ValueError):
        entry["changes"] = {}
    return entry
