"""The begin listener sends one ``BEGIN IMMEDIATE`` for a writer and one ``BEGIN`` for a reader.

``create_sqlite_engine`` registers ``begin_transaction`` on every engine; here a fake stands in for
the SQLAlchemy ``Connection`` it is handed, so no database is opened. That the listener makes DDL
transactional and lets a second writer wait is shown on a real file by
``tests/infrastructure/test_transactions.py``.

The guard below keeps writers on ``storage.sqlite.write_transaction``: an ``engine.begin()``
anywhere else in ``app/`` would open a deferred transaction, which fails instead of waiting once it
has read and another connection writes.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from pathlib import Path

import pytest

from app.core.transactions import WRITER, begin_transaction

BACKEND_ROOT = Path(__file__).resolve().parents[2]
WRITE_TRANSACTION_HOME = "app/storage/sqlite.py"


class FakeConnection:
    """Execution options in, statements out: the two things the listener touches."""

    def __init__(self, options: Mapping[str, object]) -> None:
        self.options = options
        self.statements: list[str] = []

    def get_execution_options(self) -> Mapping[str, object]:
        return self.options

    def exec_driver_sql(self, statement: str, /) -> object:
        self.statements.append(statement)
        return None


def test_the_begin_listener_is_a_plain_module_function() -> None:
    assert inspect.isfunction(begin_transaction)
    assert begin_transaction.__qualname__ == "begin_transaction"


def test_a_writer_begins_immediate() -> None:
    connection = FakeConnection({WRITER: True})

    begin_transaction(connection)

    assert connection.statements == ["BEGIN IMMEDIATE"]


@pytest.mark.parametrize(
    "options",
    [{}, {WRITER: False}, {WRITER: "true"}, {"isolation_level": "SERIALIZABLE"}],
    ids=["no-option", "writer-false", "writer-not-a-bool", "other-option"],
)
def test_a_reader_begins_deferred(options: Mapping[str, object]) -> None:
    connection = FakeConnection(options)

    begin_transaction(connection)

    assert connection.statements == ["BEGIN"]


def begin_calls(source: str, filename: str = "<source>") -> list[str]:
    """Every ``<expression>.begin()`` in ``source``, as ``file:line: call``."""
    return [
        f"{filename}:{node.lineno}: {ast.unparse(node)}"
        for node in ast.walk(ast.parse(source, filename))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "begin"
        and not node.args
        and not node.keywords
    ]


def _app_sources() -> dict[str, str]:
    root = BACKEND_ROOT / "app"
    return {
        path.relative_to(BACKEND_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def test_app_opens_a_write_transaction_only_through_write_transaction() -> None:
    sources = _app_sources()
    found = [
        call
        for name, source in sources.items()
        if name != WRITE_TRANSACTION_HOME
        for call in begin_calls(source, name)
    ]

    assert found == [], "Open a writing transaction with write_transaction(engine):\n" + "\n".join(
        found
    )
    # Positive control: the scan sees the one begin() that write_transaction itself makes.
    assert [call.split(": ", 1)[1] for call in begin_calls(sources[WRITE_TRANSACTION_HOME])] == [
        "connection.begin()"
    ]


@pytest.mark.parametrize(
    "source",
    [
        "with engine.begin() as connection:\n    pass",
        "with self.engine.begin() as conn:\n    pass",
        "transaction = connection.begin()",
        "with lock, engine.begin() as conn:\n    pass",
    ],
)
def test_the_guard_flags_a_transaction_opened_by_hand(source: str) -> None:
    assert begin_calls(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "with write_transaction(engine) as connection:\n    pass",
        "with runner.migration_transaction(engine) as connection:\n    pass",
        "with engine.connect() as connection:\n    pass",
        "savepoint = connection.begin_nested()",
        "note = 'engine.begin() inside a string is not a call'",
    ],
)
def test_the_guard_accepts_a_writer_a_reader_and_a_savepoint(source: str) -> None:
    assert begin_calls(source) == []
