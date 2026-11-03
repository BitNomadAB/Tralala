from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Unpack

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection

from ..core.config import Settings
from ..db.generated.registry import BoardsRow
from ..repositories.board_rows import BoardChanges
from ..repositories.sql.board_rows import SqlBoardRowRepository
from .sqlite import create_sqlite_engine, utcnow, write_transaction


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
        with write_transaction(self.engine) as conn:
            yield conn

    @contextmanager
    def reader(self) -> Generator[Connection]:
        """A connection that never commits: anything it changed is rolled back when it closes."""
        with self.engine.connect() as conn:
            yield conn

    def read(
        self, statement: str | TextClause, params: Mapping[str, object] | None = None
    ) -> list[dict[str, object]]:
        """Every row as a dict. A string is SQL text; a prepared statement is passed as it is."""
        if isinstance(statement, str):
            statement = text(statement)
        with self.reader() as conn:
            return [dict(row) for row in conn.execute(statement, params or {}).mappings()]

    def read_one(
        self, statement: str | TextClause, params: Mapping[str, object] | None = None
    ) -> dict[str, object] | None:
        rows = self.read(statement, params)
        return rows[0] if rows else None

    # --- boards ---------------------------------------------------------------------------------
    # The Migration Manager reads and writes board rows through these; the SQL is the board-row
    # repository's, so it exists once.

    def board(self, board_id: str) -> BoardsRow | None:
        with self.reader() as conn:
            return SqlBoardRowRepository(conn).get(board_id)

    def update_board(self, board_id: str, **fields: Unpack[BoardChanges]) -> None:
        """Write ``fields``, editable columns of the board row; nothing when there are none."""
        if not fields:
            return
        with self.connect() as conn:
            SqlBoardRowRepository(conn).update(board_id, fields, now=utcnow())

    def dispose(self) -> None:
        self.engine.dispose()
