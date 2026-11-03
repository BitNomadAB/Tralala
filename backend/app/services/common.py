from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection

from ..core import sql
from ..core.errors import Conflict, ValidationFailure
from ..repositories.sql.cards import SqlCardRepository
from ..repositories.sql.idempotency import SqlBoardIdempotencyRepository
from . import idempotency
from .ordering import place

# What the helpers below format into SQL text (see core/sql.py). A positioned table's siblings are
# the rows its filter of the same name selects; ``other`` leaves out the row being moved. Lists and
# cards are placed by their repositories (``ListRepository``, ``CardRepository``).
_POSITIONED_TABLES = ("checklists", "checklist_items")
_SIBLING_FILTERS: sql.Filters = (
    ("checklists", "card_id = :card_id"),
    ("checklist_items", "checklist_id = :checklist_id"),
    ("other", "id != :id"),
)


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


def decorate_cards(
    conn: Connection, board_id: str, cards: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each card with its board, labels and counts, as ``CardService`` shows them; for the card
    search until it is converted (GCS-T00e part 3)."""
    repository = SqlCardRepository(conn)
    ids = [card["id"] for card in cards]
    labels = repository.labels(ids)
    counts = repository.counts(ids)
    decorated = []
    for card in cards:
        entry = dict(card)
        entry["board_id"] = board_id
        entry["labels"] = [
            {"id": label.id, "name": label.name, "color": label.color}
            for label in labels[card["id"]]
        ]
        entry["checklist_total"] = counts[card["id"]].checklist_total
        entry["checklist_completed"] = counts[card["id"]].checklist_completed
        entry["comment_count"] = counts[card["id"]].comment_count
        decorated.append(entry)
    return decorated


def request_fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_idempotency(
    conn: Connection, *, actor_id: str, key: str | None, fingerprint: str
) -> Any:
    """Return the stored response for a replayed idempotency key, or None."""
    if not key:
        return None
    return idempotency.stored_answer(
        SqlBoardIdempotencyRepository(conn),
        actor_id=actor_id,
        key=key,
        fingerprint=fingerprint,
        now=datetime.now(UTC),
    )


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
    idempotency.remember(
        SqlBoardIdempotencyRepository(conn),
        actor_id=actor_id,
        key=key,
        fingerprint=fingerprint,
        answer=result,
        now=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
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
