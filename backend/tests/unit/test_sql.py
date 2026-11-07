"""SQL text is built from literals only: the helpers, and the allowlists services and repository
Protocols give them."""

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

import app.repositories
import app.services
from app.core import sql
from app.db.generated.registry import AGENTS_COLUMNS, REPOSITORIES_COLUMNS
from app.repositories import agents as agent_repositories
from app.repositories import board_rows, code_repositories
from app.repositories import card_notes as card_note_repositories
from app.repositories import cards as card_repositories
from app.repositories import checklists as checklist_repositories
from app.repositories import labels as label_repositories
from app.repositories import loops as loop_repositories
from app.schemas.agents import AgentCreate, AgentUpdate, RoleTemplateUpdate
from app.schemas.card_notes import CardNoteUpdate
from app.schemas.cards import CardUpdate
from app.schemas.loops import LoopUpdate
from app.schemas.repositories import RepositoryCreate, RepositoryUpdate
from app.schemas.subresources import ChecklistItemUpdate, LabelUpdate

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
FILTERS: sql.Filters = (("a", "a = :a"), ("b", "b IS NULL"), ("c", "(c LIKE :c OR d LIKE :c)"))


def _fields(model: type[BaseModel], *without: str) -> set[str]:
    return set(model.model_fields) - set(without)


def _is_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(value, tuple)


def _allowlist_modules() -> list[ModuleType]:
    """Every service and every repository Protocol module (``sql/`` takes its lists from there)."""
    modules = [
        importlib.import_module(f"app.services.{info.name}")
        for info in pkgutil.iter_modules(app.services.__path__)
    ]
    modules.extend(
        importlib.import_module(f"app.repositories.{info.name}")
        for info in pkgutil.iter_modules(app.repositories.__path__)
        if not info.ispkg
    )
    return modules


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
    for module in _allowlist_modules():
        for name, value in vars(module).items():
            if not name.lstrip("_").isupper() or not _is_tuple(value) or not value:
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
    # A floor, so a scan that silently finds nothing fails; allowlists that moved into
    # app/repositories/sql are compiled by the build instead (GCS-T00e; the event tables and the
    # thread filter moved with the discussion services).
    assert checked >= 12


def test_the_update_allowlists_cover_every_field_a_request_can_change() -> None:
    assert _fields(RoleTemplateUpdate) <= set(agent_repositories.ROLE_TEMPLATE_EDITABLE)
    credentials = {"api_key_ciphertext", "api_key_hint"}
    assert _fields(AgentUpdate, "api_key", "clear_api_key") | credentials <= set(
        agent_repositories.AGENT_EDITABLE
    )
    assert _fields(AgentCreate, "api_key") | credentials <= set(AGENTS_COLUMNS)
    assert _fields(LabelUpdate) <= set(label_repositories.LABEL_EDITABLE)
    assert _fields(CardNoteUpdate) <= set(card_note_repositories.CARD_NOTE_EDITABLE)
    assert _fields(ChecklistItemUpdate) <= set(checklist_repositories.CHECKLIST_ITEM_EDITABLE)
    assert _fields(LoopUpdate) | {"updated_at"} <= set(loop_repositories.LOOP_EDITABLE)
    card_fields = _fields(
        CardUpdate, "clear_due_at", "completed", "labels", "assignee_actor_id", "clear_assignee"
    )
    assert card_fields | {"completed_at", "assignee_actor_id", "updated_at"} <= set(
        card_repositories.CARD_EDITABLE
    )
    tokens = {"token_ciphertext", "token_hint"}
    assert _fields(RepositoryUpdate, "token", "clear_token") | tokens <= set(
        code_repositories.REPOSITORY_EDITABLE
    )
    assert _fields(RepositoryCreate, "token") | tokens <= set(REPOSITORIES_COLUMNS)


def _keys(required: frozenset[str], optional: frozenset[str]) -> list[str]:
    return sorted(required | optional)


def test_each_change_type_names_exactly_the_columns_its_update_may_format() -> None:
    # A service writes a typed change (pyright checks its keys); the SQL repository formats the
    # change's keys through the allowlist, which refuses any other name. The two must agree.
    pairs = [
        (
            _keys(
                board_rows.BoardChanges.__required_keys__,
                board_rows.BoardChanges.__optional_keys__,
            ),
            board_rows.BOARD_EDITABLE,
        ),
        (
            _keys(
                agent_repositories.RoleTemplateChanges.__required_keys__,
                agent_repositories.RoleTemplateChanges.__optional_keys__,
            ),
            agent_repositories.ROLE_TEMPLATE_EDITABLE,
        ),
        (
            _keys(
                agent_repositories.AgentChanges.__required_keys__,
                agent_repositories.AgentChanges.__optional_keys__,
            ),
            agent_repositories.AGENT_EDITABLE,
        ),
        (
            _keys(
                code_repositories.RepositoryChanges.__required_keys__,
                code_repositories.RepositoryChanges.__optional_keys__,
            ),
            code_repositories.REPOSITORY_EDITABLE,
        ),
        (
            _keys(
                loop_repositories.LoopChanges.__required_keys__,
                loop_repositories.LoopChanges.__optional_keys__,
            ),
            loop_repositories.LOOP_EDITABLE,
        ),
        (
            _keys(
                card_repositories.CardChanges.__required_keys__,
                card_repositories.CardChanges.__optional_keys__,
            ),
            card_repositories.CARD_EDITABLE,
        ),
        (
            _keys(
                label_repositories.LabelChanges.__required_keys__,
                label_repositories.LabelChanges.__optional_keys__,
            ),
            label_repositories.LABEL_EDITABLE,
        ),
        (
            _keys(
                card_note_repositories.CardNoteChanges.__required_keys__,
                card_note_repositories.CardNoteChanges.__optional_keys__,
            ),
            card_note_repositories.CARD_NOTE_EDITABLE,
        ),
        (
            _keys(
                checklist_repositories.ChecklistItemChanges.__required_keys__,
                checklist_repositories.ChecklistItemChanges.__optional_keys__,
            ),
            checklist_repositories.CHECKLIST_ITEM_EDITABLE,
        ),
    ]
    for keys, allowed in pairs:
        assert keys == sorted(allowed)


# --- the statements are the ones the services wrote before ---------------------------------------


# The list queries became fixed statements in app/repositories/sql/lists.py (GCS-T00c), and the
# thread list's status filter one in sql/discussions.py. The agent list's filters moved into
# app/repositories/sql/agents.py (GCS-T00d), the board
# list's and the activity feed's into sql/board_rows.py and sql/activity.py, the card list's
# into sql/cards.py, the card search's filters and FTS5 join into sql/search.py and the
# checklist siblings into sql/checklists.py (GCS-T00e); the build compiles them against the
# schema, and a unit test does not import the SQL repositories.


def test_approval_identifiers_are_the_fixed_names() -> None:
    # The event statements are fixed literals in app/repositories/sql/events.py now, one per table.
    # Changing an input invalidates its approval and everything downstream of it, in this order.
    assert loop_repositories.LOOP_APPROVAL_COLUMNS == (
        "analysis_approval_id",
        "roadmap_approval_id",
        "implementation_approval_id",
        "qa_approval_id",
    )
