"""The databases answer: the registry, and a board through the unit of work.

The health endpoint reports the process only and opens no database, so availability is checked
here on the two read paths every request takes.
"""

from __future__ import annotations

from sqlalchemy import text

from app.repositories.sql.board import SqlBoardUnitOfWork
from app.storage.registry import Registry


def test_the_registry_answers(registry: Registry, board_id: str) -> None:
    assert registry.read("SELECT 1 AS ok") == [{"ok": 1}]
    row = registry.board(board_id)
    assert row is not None
    assert row.id == board_id


def test_a_board_answers_through_the_unit_of_work(store: SqlBoardUnitOfWork, board_id: str) -> None:
    assert store.exists(board_id)
    with store.reader(board_id) as repositories:
        assert repositories.connection.execute(text("SELECT 1")).scalar_one() == 1
