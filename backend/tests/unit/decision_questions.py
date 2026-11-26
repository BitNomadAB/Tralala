"""The questions a key asked its person, as the board records them, for the decision tests.

``question_row`` is the ``decision.requested`` row ``DecisionRequestService`` writes, ``closed_row``
the ``decision.request_closed`` row of a question the person declined; ``asked_through`` and
``changes`` read a decision's history row back.
"""

from __future__ import annotations

import json

from pydantic import JsonValue

from app.db.generated.board import ActivityLogRow
from tests.unit.fakes.board import activity_row

# One person's two keys, as their credentials name them.
LAPTOP = ("cred-1", "Laptop")
DESKTOP = ("cred-2", "Desktop")


def question_row(
    entry_id: str,
    decision: str,
    entity: tuple[str, str],
    *,
    key: tuple[str, str] = LAPTOP,
    at: str,
    action: str = "decision.requested",
    reason: str | None = None,
) -> ActivityLogRow:
    entity_type, entity_id = entity
    credential_id, key_name = key
    changes: dict[str, JsonValue] = {
        "decision": decision,
        "credential_id": credential_id,
        "key_name": key_name,
        "owner_name": "Grace",
    }
    if action == "decision.requested":
        changes["via"] = "link"
    if reason is not None:
        changes["reason"] = reason
    return activity_row(
        entry_id,
        action,
        entity_id,
        actor_id="key-actor-1",
        entity_type=entity_type,
        timestamp=at,
        changes_json=json.dumps(changes),
    )


def closed_row(
    entry_id: str, decision: str, entity: tuple[str, str], *, at: str, key: tuple[str, str] = LAPTOP
) -> ActivityLogRow:
    return question_row(
        entry_id,
        decision,
        entity,
        key=key,
        at=at,
        action="decision.request_closed",
        reason="declined",
    )


def changes(row: ActivityLogRow) -> dict[str, JsonValue]:
    found: JsonValue = json.loads(row.changes_json)
    assert isinstance(found, dict)
    return found


def through(*keys: tuple[str, str]) -> list[JsonValue]:
    """``asked_through`` as a decision row carries it for these keys, oldest question first."""
    return [{"credential_id": key[0], "key_name": key[1], "via": "link"} for key in keys]
