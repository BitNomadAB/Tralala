"""Programmatic Alembic control for the registry and board schema chains.

Both chains live under ``backend/migrations`` and are selected by name; every SQLite database
keeps its own revision in ``alembic_version``. Nothing outside this module and
``MigrationManager`` may change a schema.

Alembic commands run one at a time per process. For the length of a command Alembic makes its
``EnvironmentContext`` the module ``alembic.context`` and, while revisions run, its ``Operations``
the module ``alembic.op`` (``EnvironmentContext.__enter__`` and ``Operations.context`` write them
into those modules' globals and delete them again on exit). Two commands in two threads overwrite
and delete each other's, and requests run in a thread pool, so two board creations at once, or a
creation beside an import or a migration, would both fail. ``_ALEMBIC_LOCK`` is held around every
command. It is the innermost lock: it is taken after the board's lock (when the caller holds one)
and after the database's write lock (``migration_transaction`` sends ``BEGIN IMMEDIATE`` first),
and the block holding it runs nothing but the command, whose env.py and revisions import nothing
from the application, so it never waits for another lock. ``MigrationContext.configure`` and
``ScriptDirectory`` install no globals and need no lock. ``tests/unit/test_alembic_lock.py`` keeps
it that way.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection, Engine

from ..sqlite import write_transaction

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

# Held around every Alembic command in this process; see the module docstring.
_ALEMBIC_LOCK = threading.Lock()

CHAIN_BASELINES = {
    "registry": "0001_registry_initial",
    "board": "0001_board_initial",
}

# Tables that prove a database predates Alembic version tracking.
LEGACY_TABLE_MARKERS = {
    "registry": {"boards", "actors"},
    "board": {"board_metadata", "lists", "cards"},
}


def _config(chain: str, connection: Connection | None = None) -> Config:
    if chain not in CHAIN_BASELINES:
        raise ValueError(f"Unknown migration chain: {chain}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("version_locations", str(MIGRATIONS_DIR / chain / "versions"))
    config.set_main_option("path_separator", "os")
    config.attributes["chain"] = chain
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def script_directory(chain: str) -> ScriptDirectory:
    """The revisions of one chain, as Alembic reads them from its versions directory."""
    return ScriptDirectory.from_config(_config(chain))


@lru_cache(maxsize=2)
def head_revision(chain: str) -> str:
    head = script_directory(chain).get_current_head()
    if head is None:
        raise RuntimeError(f"Migration chain {chain} has no head revision")
    return head


@lru_cache(maxsize=2)
def revision_count(chain: str) -> int:
    """Number of revisions in the chain; stored in the human-facing schema_version columns."""
    return len(list(script_directory(chain).walk_revisions()))


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def table_names(connection: Connection) -> set[str]:
    rows = connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def has_legacy_schema(chain: str, connection: Connection) -> bool:
    return LEGACY_TABLE_MARKERS[chain] <= table_names(connection)


def stamp(chain: str, connection: Connection, revision: str | None = None) -> None:
    config = _config(chain, connection)
    target = revision or CHAIN_BASELINES[chain]
    with _ALEMBIC_LOCK:
        command.stamp(config, target)


def upgrade(chain: str, connection: Connection, revision: str = "head") -> None:
    config = _config(chain, connection)
    with _ALEMBIC_LOCK:
        command.upgrade(config, revision)


@contextmanager
def migration_transaction(engine: Engine) -> Iterator[Connection]:
    """The one transaction an upgrade runs in, opened as a writer (``BEGIN IMMEDIATE``).

    Alembic joins a transaction its caller has opened, and the engine sends the BEGIN itself
    (``core/transactions.py``), so every revision's DDL runs inside this one: a revision that fails
    leaves the schema and ``alembic_version`` as they were. Python's ``sqlite3`` alone would commit
    each DDL statement that runs before the first INSERT, UPDATE or DELETE.
    """
    with write_transaction(engine) as connection:
        yield connection


def create_schema(chain: str, engine: Engine) -> str:
    """Create a brand-new database at the chain head (used for new boards)."""
    with migration_transaction(engine) as connection:
        upgrade(chain, connection)
    return head_revision(chain)
