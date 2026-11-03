"""RoleTemplateService's rules on an in-memory registry: seeding, the listing, edits and deletes.

The service runs its real code; only the repositories, the unit of work, the clock and the id source
are replaced, by the typed fakes in ``tests/unit/fakes``. The factory roles are the shipped seed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from app.core.context import ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden, NotFound
from app.db.generated.registry import RoleTemplatesRow
from app.repositories.errors import ConstraintViolationError
from app.repositories.registry import RegistryUnitOfWork
from app.schemas.agents import RoleTemplateCreate, RoleTemplateDuplicate, RoleTemplateUpdate
from app.services.agents import RoleTemplateService
from app.services.role_defaults import BUILTIN_ROLES
from tests.unit.fakes.registry import (
    CREATED,
    FakeRegistryUnitOfWork,
    RegistryState,
    agent_row,
    registry_unit_of_work,
    role_template_row,
)

NOW = "2026-11-03T10:00:00Z"
OLD = "2000-01-01T00:00:00Z"
ADMIN = ActorContext(
    actor_id="admin-1",
    actor_type="user",
    actor_name="Ada",
    scopes=scopes_for_role("admin"),
    role="admin",
)
WRITER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Robot", scopes=frozenset({"agents:write"})
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"agents:read"})
)


def unit_of_work_is_what_the_service_needs(state: RegistryState) -> RegistryUnitOfWork:
    """Never called: pyright proves the fake unit of work fits the Protocol the service takes."""
    return registry_unit_of_work(state)


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Roles:
    state: RegistryState
    store: FakeRegistryUnitOfWork
    service: RoleTemplateService


def make_roles(*rows: tuple[str, str]) -> Roles:
    """Role templates by (id, name); the first is the built-in ``coordinator``."""
    state = RegistryState()
    for index, (role_id, name) in enumerate(rows):
        builtin = index == 0
        key = "coordinator" if builtin else None
        state.role_templates[role_id] = role_template_row(
            role_id, name=name, built_in=builtin, builtin_key=key
        )
    store = FakeRegistryUnitOfWork(state)
    return Roles(state, store, RoleTemplateService(store, clock=lambda: NOW, new_id=Ids()))


@pytest.fixture
def roles() -> Roles:
    return make_roles(("builtin", "Coordinator"), ("writer", "Writer"))


# --- seeding -------------------------------------------------------------------------------------


def test_a_fresh_registry_gets_every_factory_role_once() -> None:
    empty = make_roles()
    assert empty.service.seed_defaults() == len(BUILTIN_ROLES)
    assert empty.service.seed_defaults() == 0
    seeded = {row.builtin_key: row for row in empty.state.role_templates.values()}
    for role in BUILTIN_ROLES:
        row = seeded[role["key"]]
        assert (row.name, row.description, row.scope) == (
            role["name"],
            role["description"],
            role["scope"],
        )
        assert row.system_prompt == row.default_system_prompt == role["prompt"]
        assert (row.built_in, row.created_at, row.updated_at) == (1, NOW, NOW)
    assert empty.store.commits == 2


def _seeded_with(change: Callable[[RoleTemplatesRow], RoleTemplatesRow]) -> tuple[Roles, str]:
    """A seeded registry whose first factory role was changed by ``change``, long ago."""
    roles = make_roles()
    roles.service.seed_defaults()
    key = BUILTIN_ROLES[0]["key"]
    row = next(row for row in roles.state.role_templates.values() if row.builtin_key == key)
    roles.state.role_templates[row.id] = change(row).__replace__(updated_at=OLD)
    return roles, row.id


def test_an_untouched_factory_role_follows_a_new_factory_text() -> None:
    roles, role_id = _seeded_with(
        lambda row: row.__replace__(system_prompt="old", default_system_prompt="old")
    )
    roles.service.seed_defaults()
    row = roles.state.role_templates[role_id]
    prompt = BUILTIN_ROLES[0]["prompt"]
    assert (row.system_prompt, row.default_system_prompt, row.updated_at) == (prompt, prompt, NOW)


def test_a_customized_factory_role_keeps_its_prompt_and_only_its_factory_copy_moves() -> None:
    roles, role_id = _seeded_with(
        lambda row: row.__replace__(system_prompt="mine", default_system_prompt="old factory")
    )
    roles.service.seed_defaults()
    row = roles.state.role_templates[role_id]
    assert (row.system_prompt, row.default_system_prompt) == ("mine", BUILTIN_ROLES[0]["prompt"])
    assert row.updated_at == OLD


def test_an_unchanged_factory_role_keeps_its_time_and_its_scope_follows_the_seed() -> None:
    wrong_scope = "board" if BUILTIN_ROLES[0]["scope"] == "organisation" else "organisation"
    roles, role_id = _seeded_with(lambda row: row.__replace__(scope=wrong_scope))
    roles.service.seed_defaults()
    row = roles.state.role_templates[role_id]
    assert (row.scope, row.updated_at) == (BUILTIN_ROLES[0]["scope"], OLD)


def test_seeding_a_name_a_person_already_took_fails_as_a_whole() -> None:
    roles = make_roles()
    taken = BUILTIN_ROLES[-1]["name"].upper()
    roles.state.role_templates["mine"] = role_template_row("mine", name=taken)
    with pytest.raises(ConstraintViolationError):
        roles.service.seed_defaults()
    assert set(roles.state.role_templates) == {"mine"}
    assert roles.store.rollbacks == 1


# --- the listing ---------------------------------------------------------------------------------


def test_the_listing_puts_built_ins_first_then_names_without_regard_to_case(roles: Roles) -> None:
    roles.state.role_templates["apple"] = role_template_row("apple", name="apple")
    roles.state.role_templates["banana"] = role_template_row("banana", name="Banana")
    assert [role["id"] for role in roles.service.list()] == ["builtin", "apple", "banana", "writer"]


def test_an_entry_says_whether_it_was_customized_and_never_shows_the_factory_copy(
    roles: Roles,
) -> None:
    roles.state.role_templates["builtin"] = roles.state.role_templates["builtin"].__replace__(
        system_prompt="Customized."
    )
    roles.state.agents = {
        "a": agent_row("a", role_template_id="builtin"),
        "b": agent_row("b", role_template_id="builtin"),
        "c": agent_row("c", role_template_id=None, role_prompt_override="Me."),
    }
    entry = roles.service.get("builtin")
    assert list(entry) == [
        "id",
        "name",
        "description",
        "system_prompt",
        "builtin_key",
        "created_at",
        "updated_at",
        "scope",
        "built_in",
        "customized",
        "agent_count",
    ]
    assert (entry["built_in"], entry["customized"], entry["agent_count"]) == (True, True, 2)
    assert roles.service.get("writer")["customized"] is False
    assert roles.service.get("writer")["agent_count"] == 0


def test_an_unknown_template_is_not_found(roles: Roles) -> None:
    assert roles.service.find("nothing") is None
    with pytest.raises(NotFound, match="Role template not found"):
        roles.service.get("nothing")


# --- commands ------------------------------------------------------------------------------------


def test_a_new_template_is_a_board_profile_whose_prompt_is_its_own_factory_copy(
    roles: Roles,
) -> None:
    payload = RoleTemplateCreate(name="Reviewer", description="Reads", system_prompt="Review.")
    created = roles.service.create(ADMIN, payload)
    row = roles.state.role_templates["new-1"]
    assert (created["id"], created["scope"], created["built_in"]) == ("new-1", "board", False)
    assert (row.default_system_prompt, row.builtin_key, row.created_at) == ("Review.", None, NOW)


def test_a_name_another_template_has_in_any_case_is_taken(roles: Roles) -> None:
    with pytest.raises(Conflict) as caught:
        roles.service.create(ADMIN, RoleTemplateCreate(name="WRITER", system_prompt="x"))
    assert (caught.value.code, caught.value.details) == (
        "role_template_name_taken",
        {"name": "WRITER"},
    )
    assert roles.store.rollbacks == 1


def test_an_edit_writes_what_it_names_and_stamps_the_time(roles: Roles) -> None:
    updated = roles.service.update(
        ADMIN, "writer", RoleTemplateUpdate(description="Writes well", system_prompt="Write.")
    )
    row = roles.state.role_templates["writer"]
    assert (row.name, row.description, row.system_prompt) == ("Writer", "Writes well", "Write.")
    assert (row.default_system_prompt, row.updated_at) == ("You are writer.", NOW)
    assert updated["customized"] is True


def test_an_empty_edit_changes_nothing(roles: Roles) -> None:
    assert roles.service.update(ADMIN, "writer", RoleTemplateUpdate())["updated_at"] == CREATED
    assert roles.store.commits == 0


def test_renaming_to_a_taken_name_names_the_name_asked_for(roles: Roles) -> None:
    with pytest.raises(Conflict) as caught:
        roles.service.update(ADMIN, "writer", RoleTemplateUpdate(name="coordinator"))
    assert caught.value.details == {"name": "coordinator"}
    assert roles.state.role_templates["writer"].name == "Writer"


def test_a_duplicate_is_a_new_template_with_the_same_text_and_scope(roles: Roles) -> None:
    roles.state.role_templates["builtin"] = roles.state.role_templates["builtin"].__replace__(
        scope="organisation"
    )
    copy = roles.service.duplicate(ADMIN, "builtin", RoleTemplateDuplicate())
    assert (copy["name"], copy["scope"], copy["built_in"]) == (
        "Coordinator (copy)",
        "organisation",
        False,
    )
    named = roles.service.duplicate(ADMIN, "writer", RoleTemplateDuplicate(name="  Scribe  "))
    assert named["name"] == "Scribe"
    with pytest.raises(Conflict):
        roles.service.duplicate(ADMIN, "builtin", RoleTemplateDuplicate())


def test_restoring_brings_back_the_factory_prompt_of_a_built_in_only(roles: Roles) -> None:
    roles.state.role_templates["builtin"] = roles.state.role_templates["builtin"].__replace__(
        system_prompt="Customized.", default_system_prompt="Factory."
    )
    restored = roles.service.restore_defaults(ADMIN, "builtin")
    assert (restored["system_prompt"], restored["updated_at"]) == ("Factory.", NOW)
    with pytest.raises(Conflict) as caught:
        roles.service.restore_defaults(ADMIN, "writer")
    assert caught.value.code == "role_template_not_builtin"


def test_deleting_a_template_leaves_its_agents_without_one(roles: Roles) -> None:
    roles.state.agents = {"a": agent_row("a", role_template_id="writer")}
    roles.service.delete(ADMIN, "writer")
    assert "writer" not in roles.state.role_templates
    assert roles.state.agents["a"].role_template_id is None


def test_a_built_in_cannot_be_deleted(roles: Roles) -> None:
    with pytest.raises(Conflict) as caught:
        roles.service.delete(ADMIN, "builtin")
    assert caught.value.code == "role_template_builtin"
    assert "builtin" in roles.state.role_templates


def test_each_command_asks_for_its_scope(roles: Roles) -> None:
    create = RoleTemplateCreate(name="X", system_prompt="x")
    with pytest.raises(Forbidden):
        roles.service.create(READER, create)
    with pytest.raises(Forbidden):
        roles.service.update(READER, "writer", RoleTemplateUpdate(name="Y"))
    with pytest.raises(Forbidden):
        roles.service.duplicate(READER, "writer", RoleTemplateDuplicate())
    with pytest.raises(Forbidden):
        roles.service.restore_defaults(WRITER, "builtin")
    with pytest.raises(Forbidden):
        roles.service.delete(WRITER, "writer")
    assert roles.store.commits == 0
