"""The build's schema rules, held to fixed schema descriptions (no database, no migration).

Every column that names a row has a foreign key or one reasoned list entry, every foreign key
starts an index and every foreign key declares its ON DELETE rule; every table a revision creates
after the listed ones is STRICT. ``python -m tools.dbgen`` runs the same functions over the migrated
schema and stops on the first problem.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from tools.dbgen import rules
from tools.dbgen.rules import Column, Exceptions, ForeignKey, Index, Table

NO_LISTS: Mapping[str, Exceptions] = {}


def column(name: str, *, nullable: bool = True) -> Column:
    return Column(name=name, declared="VARCHAR", python="str", nullable=nullable)


def parent() -> Table:
    return Table(name="loops", columns=(column("id", nullable=False),), strict=True)


def child(
    *columns: Column,
    keys: tuple[ForeignKey, ...] = (),
    indexes: tuple[Index, ...] = (),
) -> Table:
    return Table(
        name="phases",
        columns=(column("id", nullable=False), *columns),
        foreign_keys=keys,
        indexes=(Index("sqlite_autoindex_phases_1", ("id",)), *indexes),
        strict=True,
    )


def key(*columns: str, on_delete: str = "RESTRICT") -> ForeignKey:
    return ForeignKey(
        columns=columns, parent="loops", parent_columns=("id",) * len(columns), on_delete=on_delete
    )


def references(table: Table, lists: Mapping[str, Exceptions] = NO_LISTS) -> list[str]:
    return rules.rule_reference_columns_have_a_foreign_key({"board": [parent(), table]}, lists)


def indexed(table: Table) -> list[str]:
    return rules.rule_foreign_keys_are_indexed({"board": [parent(), table]})


def on_delete(table: Table) -> list[str]:
    return rules.rule_foreign_keys_declare_on_delete({"board": [parent(), table]})


# --- every reference column has a foreign key ---------------------------------------------------


@pytest.mark.parametrize("name", ["loop_id", "approved_by"])
def test_a_reference_column_without_a_foreign_key_stops_the_build(name: str) -> None:
    assert references(child(column(name))) == [
        f"board: phases.{name} names a row but has no foreign key; add one in a new revision,"
        " or list the column in tools/dbgen/rules.py with the reason it cannot have one"
    ]


def test_a_reference_column_with_a_foreign_key_passes() -> None:
    table = child(column("loop_id"), keys=(key("loop_id"),))
    assert references(table) == []


def test_a_column_that_only_contains_id_is_not_a_reference() -> None:
    assert references(child(column("identity"), column("idle_by_default"), column("bypass"))) == []


def test_a_listed_column_needs_no_foreign_key() -> None:
    lists = {"CROSS_DATABASE": {("board", "phases", "actor_id"): rules.REGISTRY}}
    assert references(child(column("actor_id")), lists) == []


def test_a_list_entry_for_a_column_that_has_a_foreign_key_now_is_stale() -> None:
    lists = {"UNENFORCED": {("board", "phases", "loop_id"): "blocked"}}
    table = child(column("loop_id"), keys=(key("loop_id"),))
    assert references(table, lists) == [
        "board: phases.loop_id has a foreign key now; remove it from UNENFORCED in"
        " tools/dbgen/rules.py"
    ]


def test_a_list_entry_for_a_column_the_schema_lacks_is_stale() -> None:
    lists = {"CROSS_DATABASE": {("board", "phases", "gone_id"): rules.REGISTRY}}
    assert references(child(), lists) == [
        "board: phases.gone_id is on CROSS_DATABASE but the schema has no such column;"
        " remove the entry"
    ]


def test_a_list_entry_for_another_chain_is_not_judged_without_that_chain() -> None:
    lists = {"UNENFORCED": {("registry", "agents", "role_template_id"): "blocked"}}
    assert references(child(), lists) == []


def test_a_list_entry_for_a_column_not_named_like_a_reference_is_stale() -> None:
    lists = {"NOT_REFERENCES": {("board", "phases", "name"): "a name"}}
    assert references(child(column("name")), lists) == [
        "board: phases.name is not named like a reference; remove it from NOT_REFERENCES in"
        " tools/dbgen/rules.py"
    ]


def test_a_column_on_two_lists_stops_the_build() -> None:
    entry: rules.ColumnKey = ("board", "phases", "actor_id")
    lists: Mapping[str, Exceptions] = {
        "CROSS_DATABASE": {entry: rules.REGISTRY},
        "UNENFORCED": {entry: "blocked"},
    }
    assert references(child(column("actor_id")), lists) == [
        "board: phases.actor_id is on CROSS_DATABASE and UNENFORCED; keep it on one list"
    ]


# --- every foreign key starts an index ----------------------------------------------------------


def test_a_foreign_key_without_an_index_stops_the_build() -> None:
    assert indexed(child(column("loop_id"), keys=(key("loop_id"),))) == [
        "board: phases.loop_id references loops but no index starts with it, so SQLite scans"
        " phases for every row deleted from loops; add the index in a new revision"
    ]


def test_an_index_that_has_the_column_second_does_not_count() -> None:
    table = child(
        column("loop_id"),
        column("number"),
        keys=(key("loop_id"),),
        indexes=(Index("ix_phases_number", ("number", "loop_id")),),
    )
    assert len(indexed(table)) == 1


def test_a_partial_index_does_not_count() -> None:
    table = child(
        column("loop_id"),
        keys=(key("loop_id"),),
        indexes=(Index("ux_phases_current", ("loop_id",), partial=True),),
    )
    assert len(indexed(table)) == 1


def test_an_index_that_starts_with_the_column_counts() -> None:
    table = child(
        column("loop_id"),
        column("number"),
        keys=(key("loop_id"),),
        indexes=(Index("ix_phases_loop", ("loop_id", "number")),),
    )
    assert indexed(table) == []


def test_a_composite_key_needs_its_columns_first_in_any_order() -> None:
    composite = key("plan_id", "loop_id")
    leading = Index("ix_phases_loop_plan", ("loop_id", "plan_id", "number"))
    split = Index("ix_phases_loop_number", ("loop_id", "number", "plan_id"))
    columns = (column("loop_id"), column("plan_id"), column("number"))
    assert indexed(child(*columns, keys=(composite,), indexes=(leading,))) == []
    assert indexed(child(*columns, keys=(composite,), indexes=(split,))) == [
        "board: phases.(plan_id, loop_id) references loops but no index starts with them, so"
        " SQLite scans phases for every row deleted from loops; add the index in a new revision"
    ]


def test_the_primary_key_and_the_rowid_count_as_indexes() -> None:
    table = child(column("loop_id"), keys=(key("id"),))
    assert indexed(table) == []
    rowid = Table(
        name="counters",
        columns=(Column(name="loop_id", declared="INTEGER", python="int", nullable=False),),
        foreign_keys=(key("loop_id"),),
        indexes=(Index("rowid", ("loop_id",)),),
    )
    assert rules.rule_foreign_keys_are_indexed({"board": [rowid]}) == []


# --- every foreign key declares ON DELETE --------------------------------------------------------


@pytest.mark.parametrize("rule", ["RESTRICT", "CASCADE", "SET NULL"])
def test_a_declared_on_delete_rule_passes(rule: str) -> None:
    assert on_delete(child(column("loop_id"), keys=(key("loop_id", on_delete=rule),))) == []


def test_a_foreign_key_without_an_on_delete_rule_stops_the_build() -> None:
    table = child(column("loop_id"), keys=(key("loop_id", on_delete="NO ACTION"),))
    assert on_delete(table) == [
        "board: phases.loop_id -> loops declares no ON DELETE rule; declare RESTRICT (the"
        " default), or CASCADE or SET NULL with a comment in the migration that says why"
    ]


def test_set_default_is_not_one_of_the_rules() -> None:
    table = child(column("loop_id"), keys=(key("loop_id", on_delete="SET DEFAULT"),))
    assert on_delete(table) == [
        "board: phases.loop_id -> loops says ON DELETE SET DEFAULT; declare RESTRICT (the"
        " default), or CASCADE or SET NULL with a comment in the migration that says why"
    ]


def test_set_null_on_a_not_null_column_stops_the_build() -> None:
    table = child(column("loop_id", nullable=False), keys=(key("loop_id", on_delete="SET NULL"),))
    assert on_delete(table) == [
        "board: phases.loop_id -> loops says ON DELETE SET NULL on a NOT NULL column, so every"
        " delete of a referenced row would fail; use RESTRICT or CASCADE"
    ]


# --- the lists and the rule set ------------------------------------------------------------------


def test_the_reference_rules_are_part_of_the_build() -> None:
    assert {
        rules.rule_reference_columns_have_a_foreign_key,
        rules.rule_foreign_keys_are_indexed,
        rules.rule_foreign_keys_declare_on_delete,
    } <= set(rules.SCHEMA_RULES)


def test_schema_problems_runs_every_rule_and_names_table_and_column() -> None:
    undeclared = key("loop_id", on_delete="NO ACTION")
    table = child(column("plan_id"), column("loop_id"), keys=(undeclared,))
    loose = Table(name="notes", columns=(column("id", nullable=False),), created_by="0016_notes")
    # A chain the lists do not name, so none of their entries is judged against this table.
    problems = rules.schema_problems({"scratch": [parent(), table, loose]})
    assert [problem.split(" ")[1] for problem in problems] == [
        "phases.plan_id",  # no foreign key
        "phases.loop_id",  # no index
        "phases.loop_id",  # no ON DELETE rule
        "notes",  # not STRICT
    ]


def test_the_cross_database_list_holds_only_board_columns_that_reference_the_registry() -> None:
    assert rules.CROSS_DATABASE
    assert {chain for chain, _table, _column in rules.CROSS_DATABASE} == {"board"}
    assert set(rules.CROSS_DATABASE.values()) == {rules.REGISTRY}


def test_every_list_entry_is_a_reference_column_with_a_reason_on_one_list() -> None:
    seen: set[tuple[str, str, str]] = set()
    for entries in rules.EXCEPTION_LISTS.values():
        for entry, reason in entries.items():
            assert entry[0] in {"registry", "board"}
            assert rules.is_reference(entry[2]), entry
            assert reason.strip(), entry
            assert entry not in seen, entry
            seen.add(entry)


def test_the_lists_are_frozen() -> None:
    for entries in (rules.CROSS_DATABASE, rules.NOT_REFERENCES, rules.UNENFORCED):
        assert isinstance(entries, MappingProxyType)


# --- STRICT tables -------------------------------------------------------------------------------

# The last revision of each chain before STRICT became the rule for new tables.
LAST_BEFORE_STRICT = {"registry": "0015_registry_foreign_keys", "board": "0011_board_foreign_keys"}
OLDER: Mapping[tuple[str, str], str] = {("board", "0008_loops"): "older"}


def table(name: str, created_by: str, *, strict: bool = False) -> Table:
    return Table(
        name=name, columns=(column("id", nullable=False),), strict=strict, created_by=created_by
    )


def strict(*tables: Table, exempt: Mapping[tuple[str, str], str] = OLDER) -> list[str]:
    return rules.rule_new_tables_are_strict({"board": list(tables)}, exempt)


def test_a_new_table_without_strict_stops_the_build_naming_chain_table_and_revision() -> None:
    assert strict(table("loops", "0008_loops"), table("notes", "0012_notes")) == [
        "board: notes is not STRICT, but revision 0012_notes created it after STRICT became the"
        " rule; create it with op.create_table(..., sqlite_strict=True)"
    ]


def test_a_new_strict_table_passes() -> None:
    assert strict(table("loops", "0008_loops"), table("notes", "0012_notes", strict=True)) == []


def test_a_table_without_a_creating_revision_must_be_strict() -> None:
    assert strict(table("loops", "0008_loops"), table("notes", "")) == [
        "board: notes is not STRICT, but no revision is known to have created it; create it with"
        " op.create_table(..., sqlite_strict=True)"
    ]
    assert strict(table("loops", "0008_loops"), table("notes", "", strict=True)) == []


def test_a_table_an_exempt_revision_created_may_stay_without_strict() -> None:
    assert strict(table("loops", "0008_loops"), table("phases", "0008_loops")) == []


def test_an_exemption_is_per_chain() -> None:
    schema = {"registry": [table("loops", "0008_loops")]}
    assert rules.rule_new_tables_are_strict(schema, OLDER) == [
        "registry: loops is not STRICT, but revision 0008_loops created it after STRICT became the"
        " rule; create it with op.create_table(..., sqlite_strict=True)"
    ]


def test_an_older_table_converted_to_strict_passes() -> None:
    converted = table("phases", "0008_loops", strict=True)
    assert strict(table("loops", "0008_loops"), converted) == []


def test_an_exemption_with_no_table_left_without_strict_is_stale() -> None:
    stale = (
        "board: revision 0008_loops is on NON_STRICT_REVISIONS, but no table it created is left"
        " without STRICT; remove the entry from tools/dbgen/rules.py"
    )
    assert strict(table("loops", "0008_loops", strict=True)) == [stale]
    assert strict(table("notes", "0012_notes", strict=True)) == [stale]


def test_an_exemption_for_another_chain_is_not_judged_without_that_chain() -> None:
    exempt = {("registry", "0001_registry_initial"): "older"}
    assert strict(table("notes", "0012_notes", strict=True), exempt=exempt) == []


def test_the_strict_rule_is_part_of_the_build() -> None:
    assert rules.rule_new_tables_are_strict in rules.SCHEMA_RULES


def test_the_exempt_revisions_are_frozen_reasoned_and_older_than_the_rule() -> None:
    assert isinstance(rules.NON_STRICT_REVISIONS, MappingProxyType)
    assert {chain for chain, _revision in rules.NON_STRICT_REVISIONS} == {"registry", "board"}
    for (chain, revision), reason in rules.NON_STRICT_REVISIONS.items():
        assert reason.strip(), revision
        # A later revision may only be listed with a reason of its own.
        if reason == rules.BEFORE_STRICT:
            assert revision <= LAST_BEFORE_STRICT[chain], revision


@pytest.mark.parametrize(
    ("version", "allowed"),
    [((3, 36, 9), False), ((3, 37, 0), True), ((3, 45, 3), True), ((4, 0, 0), True)],
)
def test_the_build_needs_a_sqlite_that_knows_strict_tables(
    version: tuple[int, int, int], allowed: bool
) -> None:
    problem = rules.sqlite_problem(version)
    if allowed:
        assert problem is None
    else:
        assert problem == (
            "SQLite 3.36.9 cannot create or describe STRICT tables, which need 3.37.0 or newer;"
            " build with a Python whose SQLite is newer"
        )


def test_a_type_strict_refuses_gets_the_types_it_takes() -> None:
    hint = rules.migration_hint('unknown datatype for notes.title: "VARCHAR"')
    assert hint.startswith(
        "; a STRICT table takes only the types INT, INTEGER, REAL, TEXT, BLOB, ANY: use sa.Text(),"
    )


def test_a_value_strict_refuses_is_explained_and_other_errors_are_left_alone() -> None:
    assert rules.migration_hint("cannot store TEXT value in INTEGER column notes.n") == (
        "; a STRICT table refuses a value that does not fit the column's type"
    )
    assert rules.migration_hint("no such table: notes") == ""


@pytest.mark.parametrize(
    ("declared", "python"),
    [("INT", "int"), ("INTEGER", "int"), ("REAL", "float"), ("TEXT", "str"), ("BLOB", "bytes")],
)
def test_every_strict_type_but_any_maps_to_one_python_type(declared: str, python: str) -> None:
    # The rows' converters check exactly these types, which a STRICT column guarantees.
    assert declared in rules.STRICT_TYPES
    assert rules.python_type(declared) == python


def test_any_has_no_single_python_type() -> None:
    assert rules.python_type("ANY") is None
