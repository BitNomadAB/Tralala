from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import Connection

from ..core import sql
from ..core.errors import Conflict, ValidationFailure
from ..storage.sqlite import utcnow
from .ordering import place

# What the helpers below format into SQL text (see core/sql.py). A positioned table's siblings are
# the rows its filter of the same name selects; ``other`` leaves out the row being moved.
_POSITIONED_TABLES = ("lists", "cards", "checklists", "checklist_items")
_SIBLING_FILTERS: sql.Filters = (
    ("lists", "loop_id = :loop_id AND archived_at IS NULL"),
    ("cards", "list_id = :list_id AND archived_at IS NULL"),
    ("checklists", "card_id = :card_id"),
    ("checklist_items", "checklist_id = :checklist_id"),
    ("other", "id != :id"),
)
# The join a label filter needs, shared by the card list and the card search.
LABEL_JOIN = " JOIN card_labels cl ON cl.card_id = c.id JOIN labels l ON l.id = cl.label_id"

_LABELS_FOR_CARDS = text(
    "SELECT cl.card_id, l.id, l.name, l.color FROM card_labels cl"
    " JOIN labels l ON l.id = cl.label_id WHERE cl.card_id IN :card_ids"
    " ORDER BY l.name"
).bindparams(bindparam("card_ids", expanding=True))
_CHECKLIST_COUNTS = text(
    "SELECT ch.card_id, COUNT(i.id) AS total, COALESCE(SUM(i.completed), 0) AS completed"
    " FROM checklists ch LEFT JOIN checklist_items i ON i.checklist_id = ch.id"
    " WHERE ch.card_id IN :card_ids GROUP BY ch.card_id"
).bindparams(bindparam("card_ids", expanding=True))
_COMMENT_COUNTS = text(
    "SELECT card_id, COUNT(*) AS total FROM comments WHERE card_id IN :card_ids"
    " GROUP BY card_id"
).bindparams(bindparam("card_ids", expanding=True))


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rows(
    conn: Connection, statement: str | TextClause, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Every row as a dict. A string is SQL text; a prepared statement is passed as it is."""
    if isinstance(statement, str):
        statement = text(statement)
    return [dict(row) for row in conn.execute(statement, params or {}).mappings().all()]


def one(
    conn: Connection, statement: str | TextClause, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    result = rows(conn, statement, params)
    return result[0] if result else None


def position_for_index(
    conn: Connection,
    table: str,
    params: dict[str, Any],
    index: int | None,
    *,
    exclude: str | None = None,
) -> int:
    """A gap-based position for a target index (0-based) among a row's siblings.

    ``table`` names which rows are siblings (lists of a Loop, cards of a list, checklists of a
    card, items of a checklist) and ``params`` binds that scope; ``exclude`` is the id of a row
    being moved, which is not its own sibling. The arithmetic is ``ordering.place``; when it asks
    for the siblings to be renumbered first, that happens here, in the caller's transaction.
    """
    if exclude is not None:
        params = {**params, "id": exclude}
    siblings = sql.where(_SIBLING_FILTERS, [table] if exclude is None else [table, "other"])
    table = sql.identifier(table, _POSITIONED_TABLES)
    current = rows(
        conn,
        "SELECT id, position"  # noqa: S608 - from _POSITIONED_TABLES and _SIBLING_FILTERS
        f" FROM {table}{siblings} ORDER BY position, id",
        params,
    )
    placement = place([(row["id"], row["position"]) for row in current], index)
    for sibling_id, position in placement.renumbered:
        conn.execute(
            text(
                f"UPDATE {table}"  # noqa: S608 - from _POSITIONED_TABLES
                " SET position = :position WHERE id = :id"
            ),
            {"position": position, "id": sibling_id},
        )
    return placement.position


def labels_for_cards(conn: Connection, card_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not card_ids:
        return {}
    result: dict[str, list[dict[str, Any]]] = {card_id: [] for card_id in card_ids}
    for row in rows(conn, _LABELS_FOR_CARDS, {"card_ids": list(card_ids)}):
        result[row["card_id"]].append({"id": row["id"], "name": row["name"], "color": row["color"]})
    return result


def card_counts(conn: Connection, card_ids: list[str]) -> dict[str, dict[str, int]]:
    if not card_ids:
        return {}
    params = {"card_ids": list(card_ids)}
    result: dict[str, dict[str, int]] = {
        card_id: {"checklist_total": 0, "checklist_completed": 0, "comment_count": 0}
        for card_id in card_ids
    }
    for row in rows(conn, _CHECKLIST_COUNTS, params):
        result[row["card_id"]]["checklist_total"] = int(row["total"])
        result[row["card_id"]]["checklist_completed"] = int(row["completed"])
    for row in rows(conn, _COMMENT_COUNTS, params):
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
