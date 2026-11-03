"""Migrate both chains into memory, read the tables back and hold them to the schema rules."""

from __future__ import annotations

import keyword
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.storage.schema import ensure_fts, runner

from . import BuildError

CHAINS = ("registry", "board")

# Tables that are not rows of the application: Alembic's bookkeeping and the FTS5 index (a search
# accelerator outside the schema contract, see app/storage/schema/fts.py) with its shadow tables.
EXCLUDED_TABLES = frozenset(
    {
        "alembic_version",
        "cards_fts",
        "cards_fts_config",
        "cards_fts_data",
        "cards_fts_docsize",
        "cards_fts_idx",
        "loop_history_fts",
        "loop_history_fts_config",
        "loop_history_fts_data",
        "loop_history_fts_docsize",
        "loop_history_fts_idx",
    }
)
# Names a generated row already uses for itself.
_RESERVED_COLUMNS = frozenset({"from_mapping"})


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    declared: str
    python: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    columns: tuple[Column, ...]


type Schema = Mapping[str, Sequence[Table]]


# --- migrations ---------------------------------------------------------------------------------


def chain_problems(chain: str) -> list[str]:
    """A chain is linear: one base (the baseline), one head, no merge and no branch point."""
    script = runner.script_directory(chain)
    problems: list[str] = []
    heads = script.get_heads()
    if len(heads) != 1:
        problems.append(
            f"{chain}: {len(heads)} heads ({', '.join(sorted(heads))}); rebase the newer revision"
            " onto the other so the chain stays linear"
        )
    revisions = list(script.walk_revisions())
    for revision in revisions:
        if not (revision.down_revision is None or isinstance(revision.down_revision, str)):
            problems.append(f"{chain}: {revision.revision} merges several revisions")
        if revision.is_branch_point:
            problems.append(f"{chain}: {revision.revision} has more than one next revision")
    bases = [revision.revision for revision in revisions if revision.down_revision is None]
    if bases != [runner.CHAIN_BASELINES[chain]]:
        problems.append(
            f"{chain}: base revision(s) {bases}, expected [{runner.CHAIN_BASELINES[chain]!r}]"
        )
    return problems


def migrate(chain: str) -> sqlite3.Connection:
    """A new in-memory database at the chain's head, migrated the way the application does it."""
    database = sqlite3.connect(":memory:", check_same_thread=False)
    engine = create_engine("sqlite://", creator=lambda: database, poolclass=StaticPool)
    try:
        with engine.begin() as connection:
            runner.upgrade(chain, connection)
        if chain == "board" and not ensure_fts(engine):
            raise BuildError(
                "this Python's SQLite cannot create FTS5 tables, so the board's search statements"
                " cannot be checked; build with a Python whose SQLite has FTS5"
            )
    finally:
        engine.dispose(close=False)
    return database


# --- tables -------------------------------------------------------------------------------------


def python_type(declared: str) -> str | None:
    """The Python type for a declared column type, by SQLite's affinity rules (datatype3 3.1).

    BOOLEAN is the one name read as more than its affinity: SQLite stores it as 0/1. A type with
    NUMERIC affinity (DATETIME, DECIMAL, ...) can hand back int, float or str, so it has no single
    Python type and is refused.
    """
    name = declared.upper()
    if name == "BOOLEAN":
        return "bool"
    if "INT" in name:
        return "int"
    if any(marker in name for marker in ("CHAR", "CLOB", "TEXT")):
        return "str"
    if "BLOB" in name:
        return "bytes"
    if any(marker in name for marker in ("REAL", "FLOA", "DOUB")):
        return "float"
    return None


def read_tables(database: sqlite3.Connection) -> list[Table]:
    """Every table outside the exclusion list, columns in declaration order."""
    names = [
        str(name)
        for (name,) in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"
        )
    ]
    tables: list[Table] = []
    for name in names:
        if name in EXCLUDED_TABLES:
            continue
        rows: list[tuple[int, str, str, int, object, int, int]] = database.execute(
            "SELECT cid, name, type, \"notnull\", dflt_value, pk, hidden"
            " FROM pragma_table_xinfo(?)",
            (name,),
        ).fetchall()
        key_columns = sum(1 for row in rows if row[5])
        columns: list[Column] = []
        for _cid, column, declared, not_null, _default, primary, hidden in rows:
            if hidden:
                raise BuildError(
                    f"{name}.{column} is a hidden column; a virtual table belongs on"
                    " EXCLUDED_TABLES in tools/dbgen/schema.py"
                )
            # An INTEGER PRIMARY KEY is the rowid and is never NULL, NOT NULL or not.
            rowid = bool(primary) and key_columns == 1 and declared.upper() == "INTEGER"
            columns.append(
                Column(
                    name=column,
                    declared=declared,
                    python=python_type(declared) or "",
                    nullable=not not_null and not rowid,
                )
            )
        tables.append(Table(name=name, columns=tuple(columns)))
    return tables


# --- rules --------------------------------------------------------------------------------------


def class_name(table: str) -> str:
    return "".join(part.capitalize() for part in table.split("_")) + "Row"


def rule_every_column_has_a_python_type(schema: Schema) -> list[str]:
    return [
        f"{chain}: {table.name}.{column.name} is declared {column.declared or 'without a type'!r},"
        " which has no single Python type; declare it TEXT, INTEGER, REAL, BLOB or BOOLEAN"
        for chain, tables in schema.items()
        for table in tables
        for column in table.columns
        if not column.python
    ]


def rule_names_fit_a_row(schema: Schema) -> list[str]:
    problems: list[str] = []
    for chain, tables in schema.items():
        seen: dict[str, str] = {}
        for table in tables:
            other = seen.setdefault(class_name(table.name), table.name)
            if other != table.name:
                problems.append(f"{chain}: {table.name} and {other} both become {other}Row")
            problems.extend(
                f"{chain}: {table.name}.{column.name} cannot be a dataclass field"
                for column in table.columns
                if not column.name.isidentifier()
                or keyword.iskeyword(column.name)
                or column.name in _RESERVED_COLUMNS
            )
    return problems


def rule_shared_tables_match(schema: Schema) -> list[str]:
    """A table both chains have must be the same table.

    SQL is checked against both databases and passes when either accepts it (see sqlcheck), which
    is exact only while a table name means one shape.
    """
    shapes: dict[str, tuple[str, tuple[Column, ...]]] = {}
    problems: list[str] = []
    for chain, tables in schema.items():
        for table in tables:
            other = shapes.setdefault(table.name, (chain, table.columns))
            if other[0] != chain and other[1] != table.columns:
                problems.append(
                    f"{table.name} differs between the {other[0]} and {chain} chains;"
                    " rename one of them"
                )
    return problems


# GCS-T18 (foreign keys and their indexes) and GCS-T22 (STRICT tables) add their rules here.
SCHEMA_RULES: tuple[Callable[[Schema], list[str]], ...] = (
    rule_every_column_has_a_python_type,
    rule_names_fit_a_row,
    rule_shared_tables_match,
)


def schema_problems(schema: Schema) -> list[str]:
    return [problem for rule in SCHEMA_RULES for problem in rule(schema)]
