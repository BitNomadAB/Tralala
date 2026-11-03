from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection

from ..core.config import Settings
from ..db.generated.registry import BoardsRow
from ..repositories.board_rows import BOARD_EDITABLE
from ..repositories.sql.board_rows import SqlBoardRowRepository
from .sqlite import create_sqlite_engine, utcnow


class Registry:
    """Central registry database: global board metadata, actors and credentials.

    ``connect`` and ``reader`` are the two ways in: the registry unit of work
    (``repositories/sql/registry.py``) is built on them, and code not converted to repositories
    yet still reads through ``read``. Every table has its repository in ``repositories/sql``; the
    board-row methods below stay for the code that still calls them.
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

    # --- boards ---------------------------------------------------------------------------------
    # BoardService and the Migration Manager read and write board rows through these until their
    # own conversion; the SQL is the board-row repository's, so it exists once.

    def board(self, board_id: str) -> dict[str, Any] | None:
        with self.reader() as conn:
            row = SqlBoardRowRepository(conn).get(board_id)
        return None if row is None else asdict(row)

    def insert_board(
        self, board_id: str, name: str, description: str, status: str, schema_version: int
    ) -> None:
        now = utcnow()
        row = BoardsRow(
            id=board_id,
            name=name,
            description=description,
            status=status,
            created_at=now,
            updated_at=now,
            archived_at=None,
            schema_version=schema_version,
            schema_revision=None,
        )
        with self.connect() as conn:
            SqlBoardRowRepository(conn).add(row)

    def update_board(self, board_id: str, **fields: Any) -> None:
        """Write the editable fields among ``fields``; any other name is ignored."""
        changes = {key: value for key, value in fields.items() if key in BOARD_EDITABLE}
        if not changes:
            return
        with self.connect() as conn:
            SqlBoardRowRepository(conn).update(board_id, changes, now=utcnow())

    def delete_board_row(self, board_id: str) -> None:
        with self.connect() as conn:
            SqlBoardRowRepository(conn).delete(board_id)

    def dispose(self) -> None:
        self.engine.dispose()
