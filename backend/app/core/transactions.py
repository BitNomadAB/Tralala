"""How a SQLite transaction begins: ``BEGIN IMMEDIATE`` for a writer, ``BEGIN`` for a reader.

Python's ``sqlite3`` driver, in its default legacy transaction control, sends BEGIN only before an
INSERT, UPDATE or DELETE. DDL that runs before the first of them commits on the spot, so a revision
that fails halfway can leave half a schema behind, and a SELECT reads outside any transaction. Every
engine (``storage/sqlite.py``) therefore turns the driver's BEGIN off (``isolation_level=None``)
and registers :func:`begin_transaction` as SQLAlchemy's ``begin`` listener, which sends the BEGIN
itself; the driver still commits and rolls back. That is SQLAlchemy's documented recipe
("Transactions with SQLite and the sqlite3 driver"), and with it DDL is transactional.

A deferred ``BEGIN`` takes no lock until the first statement, and a transaction that has read
cannot wait for the write lock: when another connection is writing, its first write fails with
``SQLITE_BUSY`` at once, because SQLite skips the busy handler where waiting could deadlock
(https://www.sqlite.org/lang_transaction.html). A writer therefore starts with ``BEGIN IMMEDIATE``,
which takes the write lock before anything is read, so a second writer waits at its own BEGIN, for
up to the busy timeout, and then reads what the first one committed. A reader starts with ``BEGIN``:
in WAL mode it blocks nobody, and its statements see one snapshot.

A connection is a writer when its execution option :data:`WRITER` is ``True``. Execution options
are SQLAlchemy's documented way to hand a custom setting to an event listener
(``Connection.execution_options`` and ``get_execution_options``);
``storage.sqlite.write_transaction`` sets this one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol

WRITER: Final = "writer"
"""The execution option that marks a connection as a writer."""

BEGIN_WRITER: Final = "BEGIN IMMEDIATE"
BEGIN_READER: Final = "BEGIN"


class Transactional(Protocol):
    """What the ``begin`` listener uses of SQLAlchemy's ``Connection``."""

    def get_execution_options(self) -> Mapping[str, object]: ...

    def exec_driver_sql(self, statement: str, /) -> object: ...


def begin_transaction(connection: Transactional) -> None:
    """The ``begin`` listener of every engine: one BEGIN, ``IMMEDIATE`` for a writer."""
    writer = connection.get_execution_options().get(WRITER) is True
    connection.exec_driver_sql(BEGIN_WRITER if writer else BEGIN_READER)
