from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..core.errors import Conflict, ValidationFailure
from ..storage.sqlite import utcnow

POSITION_GAP = 1024


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rows(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]


def one(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = rows(conn, sql, params)
    return result[0] if result else None


def _ordered(
    conn: Connection, table: str, where_sql: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    return rows(
        conn,
        f"SELECT id, position FROM {table} WHERE {where_sql} ORDER BY position, id",
        params,
    )


def normalize_positions(
    conn: Connection, table: str, where_sql: str, params: dict[str, Any]
) -> None:
    """Rewrite positions to multiples of POSITION_GAP, preserving order."""
    current = _ordered(conn, table, where_sql, params)
    for index, row in enumerate(current, start=1):
        conn.execute(
            text(f"UPDATE {table} SET position = :position WHERE id = :id"),
            {"position": index * POSITION_GAP, "id": row["id"]},
        )


def position_for_index(
    conn: Connection,
    table: str,
    where_sql: str,
    params: dict[str, Any],
    index: int | None,
) -> int:
    """Compute a gap-based position for a target index (0-based).

    Positions are integers spaced by POSITION_GAP. Inserts target the midpoint between
    neighbours; when no integer gap remains the scope is normalized first.
    """
    current = _ordered(conn, table, where_sql, params)
    if not current:
        return POSITION_GAP
    target = len(current) if index is None else max(0, min(index, len(current)))
    if target == len(current):
        return current[-1]["position"] + POSITION_GAP
    if target == 0:
        first = current[0]["position"]
        if first > 1:
            return first // 2
        normalize_positions(conn, table, where_sql, params)
        return POSITION_GAP // 2
    previous = current[target - 1]["position"]
    following = current[target]["position"]
    if following - previous <= 1:
        normalize_positions(conn, table, where_sql, params)
        current = _ordered(conn, table, where_sql, params)
        previous = current[target - 1]["position"]
        following = current[target]["position"]
    return (previous + following) // 2


def labels_for_cards(conn: Connection, card_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not card_ids:
        return {}
    placeholders = ", ".join(f":c{i}" for i in range(len(card_ids)))
    params = {f"c{i}": card_id for i, card_id in enumerate(card_ids)}
    result: dict[str, list[dict[str, Any]]] = {card_id: [] for card_id in card_ids}
    for row in rows(
        conn,
        f"SELECT cl.card_id, l.id, l.name, l.color FROM card_labels cl"
        f" JOIN labels l ON l.id = cl.label_id WHERE cl.card_id IN ({placeholders})"
        f" ORDER BY l.name",
        params,
    ):
        result[row["card_id"]].append({"id": row["id"], "name": row["name"], "color": row["color"]})
    return result


def card_counts(conn: Connection, card_ids: list[str]) -> dict[str, dict[str, int]]:
    if not card_ids:
        return {}
    placeholders = ", ".join(f":c{i}" for i in range(len(card_ids)))
    params = {f"c{i}": card_id for i, card_id in enumerate(card_ids)}
    result: dict[str, dict[str, int]] = {
        card_id: {"checklist_total": 0, "checklist_completed": 0, "comment_count": 0}
        for card_id in card_ids
    }
    for row in rows(
        conn,
        f"SELECT ch.card_id, COUNT(i.id) AS total, COALESCE(SUM(i.completed), 0) AS completed"
        f" FROM checklists ch LEFT JOIN checklist_items i ON i.checklist_id = ch.id"
        f" WHERE ch.card_id IN ({placeholders}) GROUP BY ch.card_id",
        params,
    ):
        result[row["card_id"]]["checklist_total"] = int(row["total"])
        result[row["card_id"]]["checklist_completed"] = int(row["completed"])
    for row in rows(
        conn,
        f"SELECT card_id, COUNT(*) AS total FROM comments WHERE card_id IN ({placeholders})"
        f" GROUP BY card_id",
        params,
    ):
        result[row["card_id"]]["comment_count"] = int(row["total"])
    return result


def decorate_cards(
    conn: Connection, board_id: str, cards: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ids = [card["id"] for card in cards]
    labels = labels_for_cards(conn, ids)
    counts = card_counts(conn, ids)
    decorated = []
    for card in cards:
        entry = dict(card)
        entry["board_id"] = board_id
        entry["labels"] = labels.get(card["id"], [])
        entry.update(counts.get(card["id"], {}))
        decorated.append(entry)
    return decorated


def resolve_label_ids(conn: Connection, names_or_ids: list[str]) -> list[str]:
    """Labels may be referenced by id or by name; unknown names are created."""
    resolved: list[str] = []
    for reference in names_or_ids:
        reference = reference.strip()
        if not reference:
            continue
        found = one(
            conn, "SELECT id FROM labels WHERE id = :ref OR name = :ref", {"ref": reference}
        )
        if found is None:
            from uuid import uuid4

            new_id = str(uuid4())
            conn.execute(
                text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)"),
                {"id": new_id, "name": reference, "color": "#64748b"},
            )
            found = {"id": new_id}
        if found["id"] not in resolved:
            resolved.append(found["id"])
    return resolved


def set_card_labels(conn: Connection, card_id: str, label_ids: list[str]) -> None:
    conn.execute(text("DELETE FROM card_labels WHERE card_id = :id"), {"id": card_id})
    for label_id in label_ids:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (:card_id, :label_id)"
            ),
            {"card_id": card_id, "label_id": label_id},
        )


def request_fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_idempotency(
    conn: Connection, *, actor_id: str, key: str | None, fingerprint: str
) -> dict[str, Any] | None:
    """Return the stored response for a replayed idempotency key, or None."""
    if not key:
        return None
    existing = one(
        conn,
        "SELECT request_hash, response_json, expires_at FROM idempotency_records"
        " WHERE actor_id = :actor_id AND idempotency_key = :key",
        {"actor_id": actor_id, "key": key},
    )
    if existing is None:
        return None
    if existing["request_hash"] != fingerprint:
        raise Conflict(
            "Idempotency key was already used with a different payload",
            code="idempotency_key_reused",
        )
    if existing["expires_at"] >= utcnow():
        return json.loads(existing["response_json"])
    conn.execute(
        text(
            "DELETE FROM idempotency_records WHERE actor_id = :actor_id AND idempotency_key = :key"
        ),
        {"actor_id": actor_id, "key": key},
    )
    return None


def store_idempotency(
    conn: Connection,
    *,
    actor_id: str,
    key: str | None,
    fingerprint: str,
    result: dict[str, Any],
    ttl_seconds: int,
) -> None:
    if not key:
        return
    now = utcnow()
    expires_at = iso_utc(datetime.now(UTC) + timedelta(seconds=ttl_seconds))
    conn.execute(
        text(
            "INSERT OR REPLACE INTO idempotency_records"
            " (actor_id, idempotency_key, request_hash, response_json, created_at, expires_at)"
            " VALUES (:actor_id, :key, :hash, :response, :now, :expires_at)"
        ),
        {
            "actor_id": actor_id,
            "key": key,
            "hash": fingerprint,
            "response": json.dumps(result),
            "now": now,
            "expires_at": expires_at,
        },
    )


def run_idempotent(
    conn: Connection,
    *,
    actor_id: str,
    key: str | None,
    fingerprint: str,
    ttl_seconds: int,
    action: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Execute an idempotent mutation. Returns (result, replayed)."""
    if not key:
        return action(), False
    cached = check_idempotency(conn, actor_id=actor_id, key=key, fingerprint=fingerprint)
    if cached is not None:
        return cached, True
    result = action()
    store_idempotency(
        conn,
        actor_id=actor_id,
        key=key,
        fingerprint=fingerprint,
        result=result,
        ttl_seconds=ttl_seconds,
    )
    return result, False


def archive_file_name(entry: str) -> str:
    """The bare filename of an archive member, or a rejection.

    A zip entry is attacker-controlled text, and the two hosts disagree about what separates a path:
    Windows treats ``\\`` as a separator and POSIX does not. Comparing the name to the entry after
    taking only its last component, and refusing dot entries, keeps the write inside the board's own
    attachments directory on either host.
    """
    name = entry.rsplit("/", 1)[-1]
    if name in {"", ".", ".."} or "\\" in name or "/" in name or "\x00" in name:
        raise ValidationFailure(
            "Board archive contains an invalid attachment entry", details={"entry": entry}
        )
    if Path(name).name != name:
        raise ValidationFailure(
            "Board archive contains an invalid attachment entry", details={"entry": entry}
        )
    return name


def require_mutable_card(conn: Connection, card_id: str) -> None:
    """Reject writes to subresources of a Loop that is completed, archived or cancelled.

    Every retained endpoint that reaches a Ticket passes through here, so a finished Loop stays
    read-only through comments, attachments, checklists and labels alike.
    """
    row = one(
        conn,
        "SELECT l.stage, l.completed_at, l.archived_at, l.cancelled_at FROM cards c"
        " JOIN loops l ON l.id = c.loop_id WHERE c.id = :id",
        {"id": card_id},
    )
    if row is None:
        return
    if (
        row["completed_at"] is not None
        or row["stage"] == "completed"
        or row["archived_at"] is not None
        or row["cancelled_at"] is not None
    ):
        raise Conflict(
            "This Loop is read-only", code="loop_read_only", details={"card_id": card_id}
        )


def require_mutable_checklist(conn: Connection, checklist_id: str) -> None:
    row = one(conn, "SELECT card_id FROM checklists WHERE id = :id", {"id": checklist_id})
    if row is not None:
        require_mutable_card(conn, row["card_id"])


def require_mutable_checklist_item(conn: Connection, item_id: str) -> None:
    row = one(
        conn,
        "SELECT ch.card_id FROM checklist_items i JOIN checklists ch ON ch.id = i.checklist_id"
        " WHERE i.id = :id",
        {"id": item_id},
    )
    if row is not None:
        require_mutable_card(conn, row["card_id"])
