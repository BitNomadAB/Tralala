"""Helpers for the services that still hold a connection (the Loop workflow and the rest, until
GCS-T00f and GCS-T00g convert them), and the archive entry check boards and backups share.

Each helper that applies a business rule delegates to the typed rule the converted services use, on
the SQL repositories over the caller's connection, so each rule and statement has one copy.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection

from ..core.errors import ValidationFailure
from ..repositories.sql.board import SqlBoardRepositories
from ..repositories.sql.idempotency import SqlBoardIdempotencyRepository
from . import idempotency
from .idempotency import request_fingerprint
from .loops import ensure_ticket_writable


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
    """Reject writes to a Ticket's subresources once its Loop is completed, archived or cancelled
    (``loops.ensure_ticket_writable``), in the caller's transaction."""
    ensure_ticket_writable(SqlBoardRepositories(conn), card_id)


__all__ = [
    "archive_file_name",
    "check_idempotency",
    "one",
    "request_fingerprint",
    "require_mutable_card",
    "rows",
    "run_idempotent",
    "store_idempotency",
]
