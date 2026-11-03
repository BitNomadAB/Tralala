"""SQL text is built from literals only: the helpers, and the allowlists the services give them."""

# The pure part of a request or database path is often a private helper; these tests call it
# on purpose (AGENTS.md, Verification contract), so private access is allowed in this file.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import importlib
import pkgutil
import re
from types import ModuleType
from typing import TypeIs

import pytest
from pydantic import BaseModel

import app.services
from app.core import sql
from app.schemas.agents import AgentCreate, AgentUpdate, RoleTemplateUpdate
from app.schemas.cards import CardUpdate
from app.schemas.loops import LoopUpdate
from app.schemas.repositories import RepositoryCreate, RepositoryUpdate
from app.schemas.subresources import ChecklistItemUpdate, LabelUpdate
from app.services import (
    agents,
    cards,
    common,
    discussions,
    events,
    loop_documents,
    loops,
    repositories,
    search,
    subresources,
)

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
FILTERS: sql.Filters = (("a", "a = :a"), ("b", "b IS NULL"), ("c", "(c LIKE :c OR d LIKE :c)"))


def _fields(model: type[BaseModel], *without: str) -> set[str]:
    return set(model.model_fields) - set(without)


def _is_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(value, tuple)


def _service_modules() -> list[ModuleType]:
    return [
        importlib.import_module(f"app.services.{info.name}")
        for info in pkgutil.iter_modules(app.services.__path__)
    ]


# --- the helpers -----------------------------------------------------------------------------


def test_an_identifier_passes_only_when_it_is_allowed() -> None:
    assert sql.identifier("name", ("name", "status")) == "name"
    for hostile in ("name; DROP TABLE boards", "Name", "", "name "):
        with pytest.raises(ValueError, match="not an allowed SQL identifier"):
            sql.identifier(hostile, ("name", "status"))


def test_a_column_list_names_every_column_in_order() -> None:
    assert sql.column_list(("id", "name", "position")) == "id, name, position"
    assert sql.column_list(("id",)) == "id"


def test_a_column_list_in_a_join_qualifies_and_prefixes_each_column() -> None:
    assert sql.column_list(("id", "name"), "a") == "a.id, a.name"
    joined = "a.id AS actor__id, a.name AS actor__name"
    assert sql.column_list(("id", "name"), "a", "actor__") == joined
    assert sql.column_list(("id",), prefix="p_") == "id AS p_id"


@pytest.mark.parametrize(
    ("table", "prefix"), [("a; DROP TABLE actors", ""), ("a", "x AS y, "), ("1a", ""), ("a.b", "")]
)
def test_a_column_list_refuses_an_alias_or_prefix_that_is_not_a_plain_name(
    table: str, prefix: str
) -> None:
    with pytest.raises(ValueError, match="is not a table alias or a column prefix"):
        sql.column_list(("id",), table, prefix)


def test_assignments_follow_the_allowlist_order_and_bind_every_column() -> None:
    allowed = ("title", "description", "version", "updated_at")
    expected = "title = :title, version = :version, updated_at = :updated_at"
    assert sql.assignments({"updated_at": 1, "title": 2, "version": 3}, allowed) == expected
    assert sql.assignments(["version", "updated_at", "title"], allowed) == expected
    assert sql.assignments({}, allowed) == ""


def test_assignments_refuse_a_column_outside_the_allowlist() -> None:
    with pytest.raises(ValueError, match="not allowed SQL identifiers: \\['id', 'x = 1 --'\\]"):
        sql.assignments({"title": 1, "id": 2, "x = 1 --": 3}, ("title",))


def test_insert_columns_pair_each_column_with_its_placeholder() -> None:
    allowed = ("id", "name", "token_hint")
    assert sql.insert_columns({"name": 1, "id": 2}, allowed) == ("id, name", ":id, :name")
    with pytest.raises(ValueError, match="not allowed SQL identifiers"):
        sql.insert_columns({"secret": 1}, allowed)


def test_where_joins_the_selected_filters_in_their_declared_order() -> None:
    assert sql.where(FILTERS, ["c", "a"]) == " WHERE a = :a AND (c LIKE :c OR d LIKE :c)"
    assert sql.where(FILTERS, {"b": None}) == " WHERE b IS NULL"
    assert sql.where(FILTERS, []) == ""
    assert sql.where(FILTERS, ["c", "a"]) == sql.where(FILTERS, ("a", "c"))


def test_where_refuses_a_filter_it_does_not_know_rather_than_dropping_it() -> None:
    with pytest.raises(ValueError, match="unknown SQL filters: \\['archived'\\]"):
        sql.where(FILTERS, ["a", "archived"])


# --- the allowlists ----------------------------------------------------------------------------


def test_every_allowlist_holds_plain_identifiers_and_every_filter_list_unique_names() -> None:
    checked = 0
    for module in _service_modules():
        for name, value in vars(module).items():
            if not name.startswith("_") or not _is_tuple(value) or not value:
                continue
            items = value
            if name.endswith(("_EDITABLE", "_COLUMNS", "_TABLES", "_SORTS")):
                assert all(
                    isinstance(column, str) and IDENTIFIER.match(column) for column in items
                ), (module, name)
                assert len(set(items)) == len(items), (module, name)
                checked += 1
            elif name.endswith("_FILTERS"):
                names: list[str] = []
                for entry in items:
                    match entry:
                        case (str() as filter_name, str()):
                            names.append(filter_name)
                        case _:
                            pytest.fail(f"{module.__name__}.{name}: {entry!r} is not a pair")
                assert len(set(names)) == len(names), (module, name)
                checked += 1
    assert checked >= 20


def test_the_update_allowlists_cover_every_field_a_request_can_change() -> None:
    assert _fields(RoleTemplateUpdate) <= set(agents._ROLE_TEMPLATE_EDITABLE)
    credentials = {"api_key_ciphertext", "api_key_hint"}
    assert _fields(AgentUpdate, "api_key", "clear_api_key") | credentials <= set(
        agents._AGENT_EDITABLE
    )
    assert _fields(AgentCreate, "api_key") | credentials <= set(agents._AGENT_COLUMNS)
    assert _fields(LabelUpdate) <= set(subresources._LABEL_EDITABLE)
    assert _fields(ChecklistItemUpdate) <= set(subresources._CHECKLIST_ITEM_EDITABLE)
    assert _fields(LoopUpdate) | {"updated_at"} <= set(loops._LOOP_EDITABLE)
    card_fields = _fields(
        CardUpdate, "clear_due_at", "completed", "labels", "assignee_actor_id", "clear_assignee"
    )
    assert card_fields | {"completed_at", "assignee_actor_id", "updated_at"} <= set(
        cards._CARD_EDITABLE
    )
    tokens = {"token_ciphertext", "token_hint"}
    assert _fields(RepositoryUpdate, "token", "clear_token") | tokens <= set(
        repositories._REPOSITORY_EDITABLE
    )
    assert _fields(RepositoryCreate, "token") | tokens <= set(repositories._REPOSITORY_COLUMNS)


# --- the statements are the ones the services wrote before ---------------------------------------


def test_sibling_scopes_are_the_clauses_the_callers_used_to_pass() -> None:
    expected = {
        ("lists",): " WHERE loop_id = :loop_id AND archived_at IS NULL",
        ("lists", "other"): " WHERE loop_id = :loop_id AND archived_at IS NULL AND id != :id",
        ("cards",): " WHERE list_id = :list_id AND archived_at IS NULL",
        ("cards", "other"): " WHERE list_id = :list_id AND archived_at IS NULL AND id != :id",
        ("checklists",): " WHERE card_id = :card_id",
        ("checklist_items",): " WHERE checklist_id = :checklist_id",
        ("checklist_items", "other"): " WHERE checklist_id = :checklist_id AND id != :id",
    }
    for selected, clause in expected.items():
        assert sql.where(common._SIBLING_FILTERS, selected) == clause
    assert set(common._POSITIONED_TABLES) == {
        name for name, _ in common._SIBLING_FILTERS if name != "other"
    }


def test_the_card_filters_keep_the_order_the_query_always_had() -> None:
    everything = [name for name, _ in cards._CARD_FILTERS if name not in {"open", "unassigned"}]
    assert sql.where(cards._CARD_FILTERS, everything) == (
        " WHERE c.loop_id = :loop_id AND c.archived_at IS NULL AND c.list_id = :list_id"
        " AND (c.title LIKE :q OR c.description LIKE :q) AND (l.id = :label OR l.name = :label)"
        " AND c.priority = :priority AND c.due_at IS NOT NULL AND c.due_at <= :due_before"
        " AND c.due_at IS NOT NULL AND c.due_at < :now AND c.completed_at IS NULL"
        " AND c.completed_at IS NOT NULL AND c.assignee_actor_id = :assignee"
    )
    assert sql.where(cards._BOARD_TICKET_FILTERS, ["open", "q"]) == (
        " WHERE c.archived_at IS NULL AND l.completed_at IS NULL AND l.archived_at IS NULL"
        " AND (c.title LIKE :q OR c.ticket_key LIKE :q)"
    )
    assert search._CARD_FTS_JOIN == " JOIN cards_fts f ON f.rowid = c.rowid"
    assert common.LABEL_JOIN == (
        " JOIN card_labels cl ON cl.card_id = c.id JOIN labels l ON l.id = cl.label_id"
    )


def test_thread_and_activity_filters_match_the_former_literals() -> None:
    # The list queries became fixed statements in app/repositories/sql/lists.py (GCS-T00c).
    assert sql.where(discussions._THREAD_FILTERS, ["status"]) == " WHERE status = :status"
    assert sql.where(search._ACTIVITY_FILTERS, {"action": "x", "entity_type": "y"}) == (
        " WHERE entity_type = :entity_type AND action = :action"
    )
    assert sql.where(agents._AGENT_FILTERS, {"enabled": 1, "q": "%a%"}) == (
        " WHERE (name LIKE :q OR description LIKE :q) AND enabled = :enabled"
    )


def test_event_and_approval_identifiers_are_the_fixed_names() -> None:
    assert events._EVENT_TABLES == ("discussion_events", "card_events")
    assert events._SCOPE_COLUMNS == ("discussion_id", "card_id")
    # Changing an input invalidates its approval and everything downstream of it, in this order.
    assert loop_documents._APPROVAL_COLUMNS == (
        "analysis_approval_id",
        "roadmap_approval_id",
        "implementation_approval_id",
        "qa_approval_id",
    )
