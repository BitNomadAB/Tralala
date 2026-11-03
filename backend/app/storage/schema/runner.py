"""Programmatic Alembic control for the registry and board schema chains.

Both chains live under ``backend/migrations`` and are selected by name; every SQLite database
keeps its own revision in ``alembic_version``. Nothing outside this module and
``MigrationManager`` may change a schema.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection, Engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"

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


@lru_cache(maxsize=2)
def head_revision(chain: str) -> str:
    head = ScriptDirectory.from_config(_config(chain)).get_current_head()
    if head is None:
        raise RuntimeError(f"Migration chain {chain} has no head revision")
    return head


@lru_cache(maxsize=2)
def revision_count(chain: str) -> int:
    """Number of revisions in the chain; stored in the human-facing schema_version columns."""
    return len(list(ScriptDirectory.from_config(_config(chain)).walk_revisions()))


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
    command.stamp(_config(chain, connection), revision or CHAIN_BASELINES[chain])


def upgrade(chain: str, connection: Connection, revision: str = "head") -> None:
    command.upgrade(_config(chain, connection), revision)


def create_schema(chain: str, engine: Engine) -> str:
    """Create a brand-new database at the chain head (used for new boards)."""
    with engine.begin() as connection:
        upgrade(chain, connection)
    return head_revision(chain)
