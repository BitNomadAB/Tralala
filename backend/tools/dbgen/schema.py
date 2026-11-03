"""Migrate both chains into memory and describe their tables for the rules and the rows."""

from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.storage.schema import ensure_fts, runner

from . import BuildError
from .rules import Column, ForeignKey, Index, Table

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


def _primary_key(database: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows: list[tuple[str, int]] = database.execute(
        "SELECT name, pk FROM pragma_table_info(?) WHERE pk > 0", (table,)
    ).fetchall()
    return tuple(name for name, _position in sorted(rows, key=lambda row: row[1]))


def _foreign_keys(database: sqlite3.Connection, table: str) -> tuple[ForeignKey, ...]:
    """Each key with its columns in order; naming no parent column means the parent's PK."""
    rows: list[tuple[int, str, str, str | None, str]] = database.execute(
        'SELECT id, "table", "from", "to", on_delete FROM pragma_foreign_key_list(?)'
        " ORDER BY id, seq",
        (table,),
    ).fetchall()
    grouped: dict[int, list[tuple[str, str, str | None, str]]] = {}
    for key, parent, column, parent_column, on_delete in rows:
        grouped.setdefault(key, []).append((parent, column, parent_column, on_delete))
    keys: list[ForeignKey] = []
    for parts in grouped.values():
        parent, on_delete = parts[0][0], parts[0][3]
        named = tuple(part[2] for part in parts if part[2] is not None)
        keys.append(
            ForeignKey(
                columns=tuple(part[1] for part in parts),
                parent=parent,
                parent_columns=(
                    named if len(named) == len(parts) else _primary_key(database, parent)
                ),
                on_delete=on_delete.upper(),
            )
        )
    return tuple(keys)


def _indexes(database: sqlite3.Connection, table: str) -> list[Index]:
    """Every index SQLite keeps for the table, including those behind PRIMARY KEY and UNIQUE."""
    found: list[Index] = []
    listed: list[tuple[str, int]] = database.execute(
        "SELECT name, partial FROM pragma_index_list(?) ORDER BY name", (table,)
    ).fetchall()
    for index, partial in listed:
        keys: list[tuple[str | None]] = database.execute(
            "SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index,)
        ).fetchall()
        found.append(
            Index(
                name=index,
                columns=tuple(column or "" for (column,) in keys),
                partial=bool(partial),
            )
        )
    return found


def read_tables(database: sqlite3.Connection) -> list[Table]:
    """Every table outside the exclusion list: columns in declaration order, keys and indexes."""
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
        indexes = _indexes(database, name)
        for _cid, column, declared, not_null, _default, primary, hidden in rows:
            if hidden:
                raise BuildError(
                    f"{name}.{column} is a hidden column; a virtual table belongs on"
                    " EXCLUDED_TABLES in tools/dbgen/schema.py"
                )
            # An INTEGER PRIMARY KEY is the rowid and is never NULL, NOT NULL or not; it is the
            # table's own b-tree key, so it is indexed without an entry in pragma_index_list.
            rowid = bool(primary) and key_columns == 1 and declared.upper() == "INTEGER"
            if rowid:
                indexes.append(Index(name="rowid", columns=(column,)))
            columns.append(
                Column(
                    name=column,
                    declared=declared,
                    python=python_type(declared) or "",
                    nullable=not not_null and not rowid,
                )
            )
        tables.append(
            Table(
                name=name,
                columns=tuple(columns),
                foreign_keys=_foreign_keys(database, name),
                indexes=tuple(indexes),
            )
        )
    return tables
