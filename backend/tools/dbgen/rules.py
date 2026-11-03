"""The migrated schema as plain data, and the structural rules it is held to.

``schema.read_tables`` describes each table of an in-memory database in the types below; every rule
in ``SCHEMA_RULES`` is a pure function from that description to a list of problems, and one problem
stops the build. Nothing here opens a database, so the unit tests hold the rules to fixed
descriptions.

**References (GCS-T18).** A column named ``*_id`` or ``*_by`` names a row, so it has a foreign key
unless one of three frozen lists says why not: ``CROSS_DATABASE`` (the row lives in another SQLite
file, which no constraint can reach), ``NOT_REFERENCES`` (the name ends like a reference but the
value is not a row of a fixed table) and ``UNENFORCED`` (a same-database reference that has no
foreign key yet, with what blocks it). An entry that no longer matches the schema is a problem too,
so the lists stay exact. Every foreign key starts an index (SQLite looks up the children of every
deleted or re-keyed parent row) and declares its ``ON DELETE`` rule: RESTRICT by default, CASCADE or
SET NULL with a comment in the migration that says why.

Most of ``UNENFORCED`` waits for one change: a SQLite table rebuild must run with foreign keys off
(the 12-step procedure in the ALTER TABLE documentation), because ``DROP TABLE`` of the old copy
fires the ``ON DELETE`` action of every row that references it. The migration runner enforces
foreign keys inside its transaction, where ``PRAGMA foreign_keys`` cannot change, so a revision can
only rebuild a table that nothing references, and cannot add a self-reference.

**STRICT tables (GCS-T22).** A table is ``STRICT`` (``op.create_table(..., sqlite_strict=True)``)
unless the revision that created it is on ``NON_STRICT_REVISIONS``, which holds, each with its
reason, the revisions from before STRICT became the rule. SQLite then refuses a value that does not
fit the declared type instead of storing it, so a generated row's checked converter cannot meet a
stray value. ``schema.migrate`` derives the creating revision: the one after which the table's name
first appears. A rebuild by ``batch_alter_table`` keeps the name and the table's mode (Alembic
copies the reflected ``sqlite_strict``), so it is not a creation and never converts an older table:
STRICT accepts only the type names INT, INTEGER, REAL, TEXT, BLOB and ANY, while most older columns
are VARCHAR, and the copy into a STRICT table fails on every stored value that does not fit, so
converting a table is a revision of its own.
"""

from __future__ import annotations

import keyword
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    declared: str
    python: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class ForeignKey:
    """A foreign key as SQLite reports it; ``on_delete`` is NO ACTION when none is declared."""

    columns: tuple[str, ...]
    parent: str
    parent_columns: tuple[str, ...]
    on_delete: str


@dataclass(frozen=True, slots=True)
class Index:
    """The key columns of an index in order (an expression is ``""``); the rowid counts as one."""

    name: str
    columns: tuple[str, ...]
    partial: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    """A table at the chain's head; ``created_by`` is the revision that created it."""

    name: str
    columns: tuple[Column, ...]
    foreign_keys: tuple[ForeignKey, ...] = ()
    indexes: tuple[Index, ...] = ()
    strict: bool = False
    created_by: str = ""


type Schema = Mapping[str, Sequence[Table]]
# (chain, table, column) -> why the column has no foreign key.
type ColumnKey = tuple[str, str, str]
type Exceptions = Mapping[ColumnKey, str]

# Names a generated row already uses for itself.
_RESERVED_COLUMNS = frozenset({"from_mapping"})


def class_name(table: str) -> str:
    return "".join(part.capitalize() for part in table.split("_")) + "Row"


# --- rows ---------------------------------------------------------------------------------------


def python_type(declared: str) -> str | None:
    """The Python type for a declared column type, by SQLite's affinity rules (datatype3 3.1).

    BOOLEAN is the one name read as more than its affinity: SQLite stores it as 0/1. A type with
    NUMERIC affinity (DATETIME, DECIMAL, ...) can hand back int, float or str, so it has no single
    Python type and is refused, as is STRICT's ANY, which keeps whatever it is given.
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


def rule_every_column_has_a_python_type(schema: Schema) -> list[str]:
    return [
        f"{chain}: {table.name}.{column.name} is declared {column.declared or 'without a type'!r},"
        " which has no single Python type; declare it TEXT, INTEGER, REAL or BLOB"
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


# --- references ---------------------------------------------------------------------------------

REFERENCE_SUFFIXES: Final = ("_id", "_by")

REGISTRY: Final = "references the registry"
_PARENT: Final = (
    "same database, but other tables reference this one: rebuilding it with foreign keys on"
    " fires their ON DELETE actions when the old copy is dropped"
)
_SELF: Final = (
    "same database, but a self-reference: a rebuild with foreign keys on clears (SET NULL),"
    " deletes (CASCADE) or refuses (RESTRICT) the copied links when the old copy is dropped"
)


def _board(columns: Mapping[tuple[str, str], str]) -> Exceptions:
    return MappingProxyType(
        {("board", table, column): why for (table, column), why in columns.items()}
    )


# Board rows that name an actor, agent, role template or board: those live in registry.sqlite. An
# actor id may also be a system actor's name ("system", "system:backup"), which is no row at all.
CROSS_DATABASE: Final = _board(
    {
        ("activity_log", "actor_id"): REGISTRY,
        ("attachments", "uploaded_by_actor_id"): REGISTRY,
        ("card_events", "actor_id"): REGISTRY,
        ("cards", "assigned_by_actor_id"): REGISTRY,
        ("cards", "assignee_actor_id"): REGISTRY,
        ("cards", "human_confirmed_by_actor_id"): REGISTRY,
        ("comment_mention_jobs", "agent_id"): REGISTRY,
        ("comment_mention_jobs", "requested_by_actor_id"): REGISTRY,
        ("comments", "actor_id"): REGISTRY,
        ("discussion_events", "actor_id"): REGISTRY,
        ("discussion_messages", "author_actor_id"): REGISTRY,
        ("discussion_participants", "participant_id"): REGISTRY,
        ("discussion_participants", "role_template_id"): REGISTRY,
        ("discussion_runs", "started_by_actor_id"): REGISTRY,
        ("discussion_threads", "created_by_actor_id"): REGISTRY,
        ("discussion_votes", "participant_id"): REGISTRY,
        ("idempotency_records", "actor_id"): REGISTRY,
        ("loop_agent_preferences", "agent_id"): REGISTRY,
        ("loop_approvals", "reviewer_actor_id"): REGISTRY,
        ("loop_documents", "author_actor_id"): REGISTRY,
        ("loop_generation_runs", "agent_id"): REGISTRY,
        ("loop_generation_runs", "created_by_actor_id"): REGISTRY,
        ("loop_history", "board_id"): REGISTRY,
        ("loop_history", "imported_by_actor_id"): REGISTRY,
        ("loop_qa_cycles", "decided_by_actor_id"): REGISTRY,
        ("loop_qa_results", "actor_id"): REGISTRY,
        ("loop_qa_results", "disposition_approved_by_actor_id"): REGISTRY,
        ("loops", "created_by_actor_id"): REGISTRY,
    }
)

NOT_REFERENCES: Final = _board(
    {
        ("activity_log", "entity_id"): (
            "names a row of whichever table entity_type says, and the audit entry outlives it"
        ),
        ("activity_log", "request_id"): "the request's correlation id, not a row",
        ("loop_dependencies", "source_id"): "a phase or a Ticket, as source_type says",
        ("loop_dependencies", "target_id"): "a phase or a Ticket, as target_type says",
        ("loop_qa_results", "scenario_id"): "a scenario inside the QA cycle's instructions JSON",
    }
)

# Same-database references without a foreign key yet. This list only shrinks: each entry says what
# blocks the constraint (see the module docstring for the rebuild rule).
UNENFORCED: Final = MappingProxyType(
    {
        ("registry", "agents", "role_template_id"): _PARENT,
        **_board(
            {
                ("cards", "phase_id"): _PARENT,
                ("cards", "plan_item_id"): _PARENT,
                ("cards", "plan_revision_id"): _PARENT,
                ("discussion_messages", "parent_message_id"): _SELF,
                ("discussion_threads", "origin_comment_id"): _PARENT,
                ("loop_documents", "source_analysis_ai_revision_id"): _SELF,
                ("loop_documents", "source_analysis_revision_id"): _SELF,
                ("loop_documents", "source_info_revision_id"): (
                    _SELF + "; also, an analysis submitted while no Info is current may name an"
                    " Info revision the board does not hold, which the service stores unchecked"
                ),
                ("loop_documents", "source_roadmap_ai_revision_id"): _SELF,
                ("loop_history", "loop_id"): _PARENT,
                ("loop_plans", "roadmap_ai_revision_id"): (
                    "same database, but NOT NULL and '' while a new plan waits for its roadmap"
                    " revisions to be linked in the same transaction"
                ),
                ("loop_plans", "roadmap_revision_id"): (
                    "same database, but NOT NULL and '' while a new plan waits for its roadmap"
                    " revisions to be linked in the same transaction"
                ),
                ("loop_qa_cycles", "card_id"): _PARENT,
                ("loop_qa_cycles", "generation_run_id"): _PARENT,
                ("loops", "active_qa_cycle_id"): _PARENT,
                ("loops", "analysis_approval_id"): _PARENT,
                ("loops", "current_plan_id"): _PARENT,
                ("loops", "history_id"): _PARENT,
                ("loops", "implementation_approval_id"): _PARENT,
                ("loops", "qa_approval_id"): _PARENT,
                ("loops", "roadmap_approval_id"): _PARENT,
            }
        ),
    }
)

EXCEPTION_LISTS: Final[Mapping[str, Exceptions]] = MappingProxyType(
    {"CROSS_DATABASE": CROSS_DATABASE, "NOT_REFERENCES": NOT_REFERENCES, "UNENFORCED": UNENFORCED}
)

# What ON DELETE may say. SQLite reports NO ACTION when a key declares nothing, so an explicit NO
# ACTION is refused as well: RESTRICT is the rule that says "not while children exist".
ON_DELETE_RULES: Final = frozenset({"RESTRICT", "CASCADE", "SET NULL"})


def is_reference(column: str) -> bool:
    return column.endswith(REFERENCE_SUFFIXES)


def _where(chain: str, table: str, columns: Sequence[str]) -> str:
    names = ", ".join(columns)
    return f"{chain}: {table}.{names}" if len(columns) == 1 else f"{chain}: {table}.({names})"


def rule_reference_columns_have_a_foreign_key(
    schema: Schema, lists: Mapping[str, Exceptions] = EXCEPTION_LISTS
) -> list[str]:
    """Every ``*_id``/``*_by`` column has a foreign key or exactly one entry with its reason."""
    problems: list[str] = []
    listed: dict[ColumnKey, list[str]] = {}
    for name, entries in lists.items():
        for key in entries:
            listed.setdefault(key, []).append(name)
    problems.extend(
        f"{key[0]}: {key[1]}.{key[2]} is on {' and '.join(names)}; keep it on one list"
        for key, names in listed.items()
        if len(names) > 1
    )
    present: set[ColumnKey] = set()
    for chain, tables in schema.items():
        for table in tables:
            constrained = {name for foreign in table.foreign_keys for name in foreign.columns}
            for column in table.columns:
                key = (chain, table.name, column.name)
                present.add(key)
                if key in listed:
                    if column.name in constrained:
                        stale = "has a foreign key now"
                    elif not is_reference(column.name):
                        stale = "is not named like a reference"
                    else:
                        continue
                    problems.append(
                        f"{chain}: {table.name}.{column.name} {stale}; remove it from"
                        f" {listed[key][0]} in tools/dbgen/rules.py"
                    )
                elif is_reference(column.name) and column.name not in constrained:
                    problems.append(
                        f"{chain}: {table.name}.{column.name} names a row but has no foreign key;"
                        " add one in a new revision, or list the column in tools/dbgen/rules.py"
                        " with the reason it cannot have one"
                    )
    problems.extend(
        f"{key[0]}: {key[1]}.{key[2]} is on {names[0]} but the schema has no such column;"
        " remove the entry"
        for key, names in listed.items()
        if key[0] in schema and key not in present
    )
    return problems


def _indexed(key: ForeignKey, table: Table) -> bool:
    """Some full index starts with the key's columns, in any order (the lookup is an equality)."""
    width = len(key.columns)
    wanted = set(key.columns)
    return any(
        not index.partial and len(index.columns) >= width and set(index.columns[:width]) == wanted
        for index in table.indexes
    )


def rule_foreign_keys_are_indexed(schema: Schema) -> list[str]:
    return [
        f"{_where(chain, table.name, key.columns)} references {key.parent} but no index starts"
        f" with {'it' if len(key.columns) == 1 else 'them'}, so SQLite scans {table.name} for"
        f" every row deleted from {key.parent}; add the index in a new revision"
        for chain, tables in schema.items()
        for table in tables
        for key in table.foreign_keys
        if not _indexed(key, table)
    ]


def rule_foreign_keys_declare_on_delete(schema: Schema) -> list[str]:
    problems: list[str] = []
    for chain, tables in schema.items():
        for table in tables:
            nullable = {column.name for column in table.columns if column.nullable}
            for key in table.foreign_keys:
                where = f"{_where(chain, table.name, key.columns)} -> {key.parent}"
                if key.on_delete not in ON_DELETE_RULES:
                    said = (
                        "declares no ON DELETE rule"
                        if key.on_delete == "NO ACTION"
                        else f"says ON DELETE {key.on_delete}"
                    )
                    problems.append(
                        f"{where} {said}; declare RESTRICT (the default), or CASCADE or SET NULL"
                        " with a comment in the migration that says why"
                    )
                elif key.on_delete == "SET NULL" and not set(key.columns) <= nullable:
                    problems.append(
                        f"{where} says ON DELETE SET NULL on a NOT NULL column, so every delete"
                        " of a referenced row would fail; use RESTRICT or CASCADE"
                    )
    return problems


# --- STRICT tables -------------------------------------------------------------------------------

# STRICT tables and pragma_table_list, which reports them, arrived in SQLite 3.37.0.
MINIMUM_SQLITE: Final = (3, 37, 0)

STRICT_TYPES: Final = ("INT", "INTEGER", "REAL", "TEXT", "BLOB", "ANY")

BEFORE_STRICT: Final = "created before STRICT became the rule for new tables"

# (chain, revision) -> why the tables that revision created may stay without STRICT. Released
# revisions never change, so an entry goes stale only when its last table without STRICT is dropped
# or converted, and is then removed. A later revision lands here only with a reason of its own (a
# rename counts as a creation, so renaming an older table without converting it needs one).
NON_STRICT_REVISIONS: Final = MappingProxyType(
    {
        ("registry", "0001_registry_initial"): BEFORE_STRICT,
        ("registry", "0003_board_templates"): BEFORE_STRICT,
        ("registry", "0004_agent_foundation"): BEFORE_STRICT,
        ("registry", "0005_accounts_and_sessions"): BEFORE_STRICT,
        ("registry", "0007_board_repositories"): BEFORE_STRICT,
        ("registry", "0009_board_repository_links"): BEFORE_STRICT,
        ("registry", "0010_board_agents"): BEFORE_STRICT,
        ("registry", "0012_user_invites"): BEFORE_STRICT,
        ("registry", "0014_board_stats"): BEFORE_STRICT,
        ("board", "0001_board_initial"): BEFORE_STRICT,
        ("board", "0003_card_assignment_attachments"): BEFORE_STRICT,
        ("board", "0004_discussions"): BEFORE_STRICT,
        ("board", "0005_discussion_run_control"): BEFORE_STRICT,
        ("board", "0006_discussion_events"): BEFORE_STRICT,
        ("board", "0007_comment_mentions"): BEFORE_STRICT,
        ("board", "0008_loops"): BEFORE_STRICT,
        ("board", "0009_loop_agent_preferences"): BEFORE_STRICT,
    }
)


def sqlite_problem(version: tuple[int, int, int]) -> str | None:
    """Why this SQLite cannot build the schema, or None."""
    if version >= MINIMUM_SQLITE:
        return None
    found = ".".join(str(part) for part in version)
    needed = ".".join(str(part) for part in MINIMUM_SQLITE)
    return (
        f"SQLite {found} cannot create or describe STRICT tables, which need {needed} or newer;"
        " build with a Python whose SQLite is newer"
    )


def migration_hint(error: str) -> str:
    """Advice to append to SQLite's message when a revision does not apply, or ``""``."""
    if "unknown datatype" in error:
        return (
            f"; a STRICT table takes only the types {', '.join(STRICT_TYPES)}: use sa.Text(),"
            " sa.Integer(), sa.REAL() or sa.LargeBinary() (a flag is an INTEGER 0/1 and a"
            " timestamp ISO 8601 TEXT, see docs/database.md)"
        )
    if "cannot store" in error:
        return "; a STRICT table refuses a value that does not fit the column's type"
    return ""


def rule_new_tables_are_strict(
    schema: Schema, exempt: Mapping[tuple[str, str], str] = NON_STRICT_REVISIONS
) -> list[str]:
    """Every table is STRICT unless the revision that created it is exempt, and every exemption
    still covers a table that is not STRICT."""
    problems: list[str] = []
    needed: set[tuple[str, str]] = set()
    for chain, tables in schema.items():
        for table in tables:
            if table.strict:
                continue
            if (chain, table.created_by) in exempt:
                needed.add((chain, table.created_by))
                continue
            created = (
                f"revision {table.created_by} created it after STRICT became the rule"
                if table.created_by
                else "no revision is known to have created it"
            )
            problems.append(
                f"{chain}: {table.name} is not STRICT, but {created}; create it with"
                " op.create_table(..., sqlite_strict=True)"
            )
    problems.extend(
        f"{chain}: revision {revision} is on NON_STRICT_REVISIONS, but no table it created is"
        " left without STRICT; remove the entry from tools/dbgen/rules.py"
        for chain, revision in exempt
        if chain in schema and (chain, revision) not in needed
    )
    return problems


SCHEMA_RULES: tuple[Callable[[Schema], list[str]], ...] = (
    rule_every_column_has_a_python_type,
    rule_names_fit_a_row,
    rule_shared_tables_match,
    rule_reference_columns_have_a_foreign_key,
    rule_foreign_keys_are_indexed,
    rule_foreign_keys_declare_on_delete,
    rule_new_tables_are_strict,
)


def schema_problems(schema: Schema) -> list[str]:
    return [problem for rule in SCHEMA_RULES for problem in rule(schema)]
