from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import Connection

from ..core import sql
from ..core.config import Settings
from .sqlite import create_sqlite_engine, utcnow

# What the registry formats into SQL text (see core/sql.py).
_BOARD_EDITABLE = (
    "name",
    "description",
    "status",
    "archived_at",
    "schema_version",
    "schema_revision",
)
_BOARD_STATS = text("SELECT * FROM board_stats WHERE board_id IN :board_ids").bindparams(
    bindparam("board_ids", expanding=True)
)


class Registry:
    """Central registry database: global board metadata, actors and credentials.

    ``connect`` and ``reader`` are the two ways in: the registry unit of work
    (``repositories/sql/registry.py``) is built on them, and code not converted to repositories
    yet still reads through ``read``. Accounts, sessions, invitations and API tokens live in
    ``repositories/sql/accounts.py``.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_sqlite_engine(settings.registry_path)

    @contextmanager
    def connect(self) -> Generator[Connection]:
        """One transaction: committed when the block ends, rolled back when it raises."""
        with self.engine.begin() as conn:
            yield conn

    @contextmanager
    def reader(self) -> Generator[Connection]:
        """A connection that never commits: anything it changed is rolled back when it closes."""
        with self.engine.connect() as conn:
            yield conn

    def read(
        self, statement: str | TextClause, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Every row as a dict. A string is SQL text; a prepared statement is passed as it is."""
        if isinstance(statement, str):
            statement = text(statement)
        with self.reader() as conn:
            return [dict(row) for row in conn.execute(statement, params or {}).mappings()]

    def read_one(
        self, statement: str | TextClause, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        rows = self.read(statement, params)
        return rows[0] if rows else None

    # --- boards -----------------------------------------------------------------

    def list_board_rows(self) -> list[dict[str, Any]]:
        return self.read("SELECT * FROM boards ORDER BY updated_at DESC, name")

    def board(self, board_id: str) -> dict[str, Any] | None:
        return self.read_one("SELECT * FROM boards WHERE id = :id", {"id": board_id})

    def insert_board(
        self, board_id: str, name: str, description: str, status: str, schema_version: int
    ) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO boards"
                    " (id, name, description, status, created_at, updated_at, archived_at,"
                    "  schema_version)"
                    " VALUES (:id, :name, :description, :status, :now, :now, NULL, :version)"
                ),
                {
                    "id": board_id,
                    "name": name,
                    "description": description,
                    "status": status,
                    "now": now,
                    "version": schema_version,
                },
            )

    def update_board(self, board_id: str, **fields: Any) -> None:
        updates = {key: value for key, value in fields.items() if key in _BOARD_EDITABLE}
        if not updates:
            return
        assignments = sql.assignments(updates, _BOARD_EDITABLE)
        with self.connect() as conn:
            conn.execute(
                text(
                    "UPDATE boards"  # noqa: S608 - from _BOARD_EDITABLE
                    f" SET {assignments}, updated_at = :updated_at WHERE id = :board_id"
                ),
                {**updates, "updated_at": utcnow(), "board_id": board_id},
            )

    def delete_board_row(self, board_id: str) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM boards WHERE id = :id"), {"id": board_id})

    # --- board counters ----------------------------------------------------------

    def board_stats(self, board_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not board_ids:
            return {}
        rows = self.read(_BOARD_STATS, {"board_ids": list(board_ids)})
        return {row["board_id"]: row for row in rows}

    def store_board_stats(
        self, board_id: str, loop_count: int, list_count: int, card_count: int, *, measured_at: str
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO board_stats"
                    " (board_id, loop_count, list_count, card_count, measured_at)"
                    " VALUES (:id, :loops, :lists, :cards, :measured_at)"
                    " ON CONFLICT(board_id) DO UPDATE SET"
                    "  loop_count = excluded.loop_count,"
                    "  list_count = excluded.list_count,"
                    "  card_count = excluded.card_count,"
                    "  measured_at = excluded.measured_at"
                ),
                {
                    "id": board_id,
                    "loops": loop_count,
                    "lists": list_count,
                    "cards": card_count,
                    "measured_at": measured_at,
                },
            )

    def forget_board_stats(self, board_id: str) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM board_stats WHERE board_id = :id"), {"id": board_id})

    def forget_all_board_stats(self) -> None:
        with self.connect() as conn:
            conn.execute(text("DELETE FROM board_stats"))

    def dispose(self) -> None:
        self.engine.dispose()
