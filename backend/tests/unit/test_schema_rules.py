"""The build's reference rules, held to fixed schema descriptions (no database, no migration).

Every column that names a row has a foreign key or one reasoned list entry, every foreign key
starts an index and every foreign key declares its ON DELETE rule. ``python -m tools.dbgen`` runs
the same functions over the migrated schema and stops on the first problem.
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
    return Table(name="loops", columns=(column("id", nullable=False),))


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
    # A chain the lists do not name, so none of their entries is judged against this table.
    problems = rules.schema_problems({"scratch": [parent(), table]})
    assert [problem.split(" ")[1] for problem in problems] == [
        "phases.plan_id",  # no foreign key
        "phases.loop_id",  # no index
        "phases.loop_id",  # no ON DELETE rule
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
