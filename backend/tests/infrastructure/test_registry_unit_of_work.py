"""The registry unit of work: a writer commits or rolls back as a whole, a reader never commits."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.repositories.sql.registry import SqlRegistryUnitOfWork

_INSERT = text("INSERT INTO infrastructure_probe (value) VALUES (:value)")
_COUNT = text("SELECT COUNT(*) FROM infrastructure_probe")


class WorkInterruptedError(Exception):
    pass


def _rows(store: SqlRegistryUnitOfWork) -> int:
    with store.reader() as repositories:
        return int(repositories.connection.execute(_COUNT).scalar_one())


@pytest.mark.usefixtures("registry_probe")
def test_a_registry_writer_that_ends_commits(registry_store: SqlRegistryUnitOfWork) -> None:
    with registry_store.writer() as repositories:
        repositories.connection.execute(_INSERT, {"value": "first"})
        repositories.connection.execute(_INSERT, {"value": "second"})

    assert _rows(registry_store) == 2


@pytest.mark.usefixtures("registry_probe")
def test_a_registry_writer_that_raises_leaves_nothing_behind(
    registry_store: SqlRegistryUnitOfWork,
) -> None:
    with pytest.raises(WorkInterruptedError), registry_store.writer() as repositories:
        repositories.connection.execute(_INSERT, {"value": "lost"})
        raise WorkInterruptedError

    assert _rows(registry_store) == 0


@pytest.mark.usefixtures("registry_probe")
def test_a_registry_reader_never_commits(registry_store: SqlRegistryUnitOfWork) -> None:
    with registry_store.reader() as repositories:
        repositories.connection.execute(_INSERT, {"value": "discarded"})

    assert _rows(registry_store) == 0
