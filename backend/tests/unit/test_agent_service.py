"""AgentService's rules on an in-memory registry: entries, sealed keys, roles, boards and probes.

The service runs its real code; only the repositories, the unit of work, the clock, the id source
and the probes are replaced. The endpoint rule is the real one (``connections.validate_endpoint``)
with a fixed resolver, and keys are sealed with the real ``core.secrets``, so a test can open what
the service stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

import pytest

from app.core.config import Settings
from app.core.context import ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.core.secrets import open_secret, open_secret_state, seal_secret
from app.repositories.registry import RegistryUnitOfWork
from app.schemas.agents import AgentCreate, AgentDuplicate, AgentTestRequest, AgentUpdate
from app.services import connections
from app.services.agents import AgentEndpoints, AgentService
from app.services.connections import CompletionProbe, EndpointProbe
from tests.unit.fakes.registry import (
    CREATED,
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    agent_row,
    board_row,
    registry_unit_of_work,
    role_template_row,
    sign_in_row,
)
from tests.unit.log_lines import events, lines

NOW = "2026-11-03T10:00:00Z"
KEY = "sk-helper-1234"
OTHER_SECRET = "an-earlier-installation-secret-" + "p" * 24
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
CONNECTED: EndpointProbe = {
    "ok": True,
    "status": "connected",
    "message": "Connected; 2 model(s) reported",
    "latency_ms": 5,
    "models": ["m1", "m2"],
}
COMPLETED: CompletionProbe = {
    "ok": True,
    "status": "completed",
    "message": "Model m1 answered: ok",
    "latency_ms": 7,
    "supports_json_schema": True,
}


def unit_of_work_is_what_the_service_needs(state: RegistryState) -> RegistryUnitOfWork:
    """Never called: pyright proves the fake unit of work fits the Protocol the service takes."""
    return registry_unit_of_work(state)


def connections_is_what_the_service_needs() -> AgentEndpoints:
    """Never called: pyright proves the real module fits the Protocol the service defaults to."""
    return connections


def _resolve(host: str) -> list[str]:
    del host
    return ["10.0.0.7"]


class Endpoints:
    """The real endpoint rule with a fixed resolver; probes answer as told and are recorded."""

    def __init__(
        self,
        *,
        models: EndpointProbe = CONNECTED,
        completion: CompletionProbe = COMPLETED,
        failure: Exception | None = None,
    ) -> None:
        self.models: EndpointProbe = models
        self.completion: CompletionProbe = completion
        self.failure = failure
        self.calls: list[tuple[str, str, str | None, float]] = []

    def validate_endpoint(self, url: str, *, allow_private: bool) -> str:
        return connections.validate_endpoint(url, allow_private=allow_private, resolve=_resolve)

    def probe_openai_compatible(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe:
        del allow_private
        self.calls.append(("models", base_url, api_key, timeout))
        if self.failure is not None:
            raise self.failure
        return self.models

    def probe_a2a(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe:
        del allow_private
        self.calls.append(("a2a", base_url, api_key, timeout))
        if self.failure is not None:
            raise self.failure
        return self.models

    def probe_completion(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str | None,
        timeout: float,
        allow_private: bool,
    ) -> CompletionProbe:
        del allow_private
        self.calls.append((f"completion {model}", base_url, api_key, timeout))
        return self.completion


def endpoints_fit(endpoints: Endpoints) -> AgentEndpoints:
    """Never called: pyright proves the stand-in fits the Protocol."""
    return endpoints


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Agents:
    state: RegistryState
    store: FakeRegistryUnitOfWork
    endpoints: Endpoints
    service: AgentService
    settings: Settings


def make_agents(settings: Settings, endpoints: Endpoints | None = None) -> Agents:
    """Templates ``board-role`` and ``org-role``; agents ``helper`` (board role, sealed key),
    ``planner`` (organisation role) and ``override`` (disabled, a2a, override only); boards
    ``board-1`` and ``board-2``."""
    state = RegistryState()
    state.role_templates = {
        "board-role": role_template_row(
            "board-role", name="Builder", updated_at="2026-11-02T08:00:00Z"
        ),
        "org-role": role_template_row("org-role", name="Architect", scope="organisation"),
    }
    state.agents = {
        "helper": agent_row(
            "helper",
            name="Helper",
            description="Helps a lot",
            role_template_id="board-role",
            model="m1",
            api_key_ciphertext=seal_secret(settings, KEY),
            api_key_hint="••••1234",
            timeout_seconds=12,
        ),
        "planner": agent_row("planner", name="planner", role_template_id="org-role"),
        "override": agent_row(
            "override",
            name="Override",
            role_prompt_override="Only me.",
            connection_type="a2a",
            base_url="http://10.0.0.6:9000",
            enabled=False,
        ),
    }
    state.boards = {"board-1": board_row("board-1"), "board-2": board_row("board-2")}
    store = FakeRegistryUnitOfWork(state)
    probes = endpoints or Endpoints()
    service = AgentService(settings, store, clock=lambda: NOW, new_id=Ids(), endpoints=probes)
    return Agents(state, store, probes, service, settings)


@pytest.fixture
def agents(settings: Settings) -> Agents:
    return make_agents(settings)


def create(**fields: str | None) -> AgentCreate:
    values: dict[str, object] = {
        "name": "Fresh",
        "role_template_id": "board-role",
        "connection_type": "openai_compatible",
        "base_url": "http://10.0.0.5:8080/v1",
    }
    values.update(fields)
    return AgentCreate.model_validate(values)


# --- entries -------------------------------------------------------------------------------------


def test_an_entry_says_a_key_exists_but_carries_neither_the_key_nor_the_override(
    agents: Agents,
) -> None:
    entry = agents.service.get("helper")
    assert list(entry) == [
        "id",
        "name",
        "description",
        "role_template_id",
        "connection_type",
        "base_url",
        "model",
        "api_key_hint",
        "temperature",
        "max_output_tokens",
        "timeout_seconds",
        "enabled",
        "last_test_status",
        "last_test_message",
        "last_tested_at",
        "supports_json_schema",
        "created_at",
        "updated_at",
        "role_template_name",
        "role_template_scope",
        "role_template_updated_at",
        "has_role_override",
        "has_api_key",
    ]
    assert (entry["has_api_key"], entry["api_key_hint"], entry["enabled"]) == (
        True,
        "••••1234",
        True,
    )
    assert (entry["role_template_name"], entry["role_template_scope"]) == ("Builder", "board")
    assert entry["role_template_updated_at"] == "2026-11-02T08:00:00Z"
    override = agents.service.get("override")
    assert (override["has_role_override"], override["has_api_key"]) == (True, False)
    assert (override["role_template_name"], override["role_template_scope"]) == (None, "board")
    assert "Only me." not in override.values()


def test_an_unknown_agent_is_not_found(agents: Agents) -> None:
    assert agents.service.find_row("nothing") is None
    with pytest.raises(NotFound, match="Agent not found"):
        agents.service.get("nothing")


def test_the_list_is_by_name_and_filters_like_sql_like(agents: Agents) -> None:
    def names(q: str | None = None, enabled: bool | None = None) -> list[str]:
        return [entry["name"] for entry in agents.service.list(q=q, enabled=enabled)]

    assert names() == ["Helper", "Override", "planner"]
    assert names(q="") == names()
    assert names(q="ELP") == ["Helper"]
    assert names(q="a lot") == ["Helper"]
    assert names(q="O_er") == ["Override"]
    assert names(q="%") == names()
    assert names(enabled=False) == ["Override"]
    assert names(q="p", enabled=True) == ["Helper", "planner"]


def test_the_directory_lists_enabled_agents_without_connection_details(agents: Agents) -> None:
    directory = agents.service.directory()
    assert directory == [
        {
            "id": "helper",
            "name": "Helper",
            "role_template_id": "board-role",
            "role_template_name": "Builder",
            "role_template_scope": "board",
        },
        {
            "id": "planner",
            "name": "planner",
            "role_template_id": "org-role",
            "role_template_name": "Architect",
            "role_template_scope": "organisation",
        },
    ]


def test_assignable_people_are_the_enabled_people_with_their_role(agents: Agents) -> None:
    agents.state.actors = {
        "ada": actor_row("ada", name="Ada"),
        "bob": actor_row("bob", name="Bob", disabled_at=CREATED),
        "bot": actor_row("bot", type_="agent", name="Bot"),
    }
    agents.state.sign_ins = {
        "ada": sign_in_row("ada", role="admin"),
        "bob": sign_in_row("bob"),
    }
    assert agents.service.assignable_people() == [
        {"id": "ada", "name": "Ada", "type": "user", "role": "admin"}
    ]


def test_a_worker_may_ask_the_boards_own_selection_of_board_profiles(agents: Agents) -> None:
    second = agent_row("second", name="Second", role_template_id="board-role")
    agents.state.agents["second"] = second
    every_board_profile = ["helper", "second"]
    assert [entry["id"] for entry in agents.service.askable_agents("board-1")] == (
        every_board_profile
    )
    agents.service.set_board_agents("board-1", ["second"])
    assert agents.service.askable_agents("board-1") == [
        {"id": "second", "name": "Second", "role_template_name": "Builder"}
    ]


# --- roles ---------------------------------------------------------------------------------------


def test_the_effective_role_is_the_template_unless_an_override_is_set(agents: Agents) -> None:
    role = agents.service.effective_role("helper")
    assert (role["system_prompt"], role["role_source"]) == ("You are board-role.", "template")
    assert (role["template_system_prompt"], role["override_system_prompt"]) == (
        "You are board-role.",
        None,
    )
    agents.state.agents["helper"] = agents.state.agents["helper"].__replace__(
        role_prompt_override="Be brief."
    )
    role = agents.service.effective_role("helper")
    assert (role["system_prompt"], role["role_source"], role["role_template_name"]) == (
        "Be brief.",
        "override",
        "Builder",
    )
    override_only = agents.service.effective_role("override")
    assert (override_only["role_template_id"], override_only["system_prompt"]) == (None, "Only me.")


def test_an_agent_whose_template_is_gone_and_has_no_override_has_no_usable_role(
    agents: Agents,
) -> None:
    del agents.state.role_templates["board-role"]
    with pytest.raises(ValidationFailure, match="no usable role") as caught:
        agents.service.effective_role("helper")
    assert caught.value.details == {"agent_id": "helper"}
    with pytest.raises(NotFound):
        agents.service.effective_role("nothing")


def test_a_snapshot_fixes_the_prompt_its_digest_and_the_time(agents: Agents) -> None:
    snapshot = agents.service.role_snapshot("helper")
    prompt = "You are board-role."
    assert snapshot == {
        "agent_id": "helper",
        "agent_name": "Helper",
        "role_template_id": "board-role",
        "role_template_name": "Builder",
        "role_template_updated_at": "2026-11-02T08:00:00Z",
        "role_source": "template",
        "system_prompt": prompt,
        "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "snapshot_at": NOW,
    }


# --- create, update, duplicate, delete -----------------------------------------------------------


def test_a_new_agent_stores_its_key_sealed_and_shows_only_the_hint(agents: Agents) -> None:
    entry = agents.service.create(ADMIN, create(api_key="sk-fresh-9876", model="m2"))
    row = agents.state.agents["new-1"]
    assert row.api_key_ciphertext is not None
    assert row.api_key_ciphertext != "sk-fresh-9876"
    assert open_secret(agents.settings, row.api_key_ciphertext) == "sk-fresh-9876"
    assert (row.api_key_hint, row.enabled, row.created_at, row.updated_at) == (
        "••••9876",
        1,
        NOW,
        NOW,
    )
    assert (entry["id"], entry["has_api_key"], entry["api_key_hint"]) == ("new-1", True, "••••9876")
    assert "sk-fresh-9876" not in str(entry)


def test_an_empty_key_stores_no_key(agents: Agents) -> None:
    agents.service.create(ADMIN, create(api_key=""))
    row = agents.state.agents["new-1"]
    assert (row.api_key_ciphertext, row.api_key_hint) == (None, None)


def test_a_new_agent_needs_a_template_that_exists_or_an_override(agents: Agents) -> None:
    with pytest.raises(ValidationFailure) as caught:
        agents.service.create(ADMIN, create(role_template_id=None))
    assert caught.value.details == {"field": "role_template_id"}
    with pytest.raises(NotFound, match="Role template not found"):
        agents.service.create(ADMIN, create(role_template_id="nothing"))
    agents.service.create(ADMIN, create(role_template_id=None, role_prompt_override="Me."))
    assert agents.state.agents["new-1"].role_prompt_override == "Me."


@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest", "http://user:secret@10.0.0.5/v1", "ftp://10.0.0.5/v1"],
)
def test_an_endpoint_the_rule_refuses_is_never_stored(agents: Agents, url: str) -> None:
    with pytest.raises(ValidationFailure):
        agents.service.create(ADMIN, create(base_url=url))
    assert "new-1" not in agents.state.agents


def test_the_stored_endpoint_is_the_one_the_rule_returns(agents: Agents) -> None:
    agents.service.create(ADMIN, create(base_url="http://llm.example.com/v1/"))
    assert agents.state.agents["new-1"].base_url == "http://llm.example.com/v1"


def test_without_injected_probes_the_real_endpoint_rule_applies(settings: Settings) -> None:
    store = FakeRegistryUnitOfWork(make_agents(settings).state)
    service = AgentService(settings, store)
    with pytest.raises(ValidationFailure):
        service.create(ADMIN, create(base_url="http://169.254.169.254/"))


def test_a_name_another_agent_has_in_any_case_is_taken(agents: Agents) -> None:
    with pytest.raises(Conflict) as caught:
        agents.service.create(ADMIN, create(name="HELPER"))
    assert (caught.value.code, caught.value.details) == ("agent_name_taken", {"name": "HELPER"})
    assert agents.store.rollbacks == 1


def test_an_edit_writes_what_it_names(agents: Agents) -> None:
    entry = agents.service.update(
        ADMIN, "helper", AgentUpdate(description="Helps more", timeout_seconds=20, enabled=False)
    )
    row = agents.state.agents["helper"]
    assert (row.description, row.timeout_seconds, row.enabled, row.updated_at) == (
        "Helps more",
        20,
        0,
        NOW,
    )
    assert open_secret(agents.settings, row.api_key_ciphertext or "") == KEY
    assert entry["enabled"] is False


def test_an_empty_edit_changes_nothing(agents: Agents) -> None:
    assert agents.service.update(ADMIN, "helper", AgentUpdate())["updated_at"] == CREATED
    assert agents.store.commits == 0


def test_a_new_key_replaces_the_old_and_clearing_wins_over_a_new_key(agents: Agents) -> None:
    agents.service.update(ADMIN, "helper", AgentUpdate(api_key="sk-rotated-5555"))
    rotated = agents.state.agents["helper"]
    assert open_secret(agents.settings, rotated.api_key_ciphertext or "") == "sk-rotated-5555"
    assert rotated.api_key_hint == "••••5555"
    agents.service.update(ADMIN, "helper", AgentUpdate(api_key="sk-x", clear_api_key=True))
    cleared = agents.state.agents["helper"]
    assert (cleared.api_key_ciphertext, cleared.api_key_hint) == (None, None)


def test_a_role_change_is_checked_against_what_the_agent_keeps(agents: Agents) -> None:
    with pytest.raises(NotFound):
        agents.service.update(ADMIN, "helper", AgentUpdate(role_template_id="nothing"))
    # The override it already has is a usable role on its own.
    agents.service.update(ADMIN, "override", AgentUpdate(role_template_id="board-role"))
    assert agents.state.agents["override"].role_template_id == "board-role"
    agents.service.update(ADMIN, "helper", AgentUpdate(role_prompt_override="Be brief."))
    assert agents.state.agents["helper"].role_prompt_override == "Be brief."


def test_a_new_endpoint_passes_the_rule_before_anything_is_written(agents: Agents) -> None:
    with pytest.raises(ValidationFailure):
        agents.service.update(
            ADMIN, "helper", AgentUpdate(name="Renamed", base_url="http://169.254.169.254/")
        )
    assert agents.state.agents["helper"].name == "Helper"
    agents.service.update(ADMIN, "helper", AgentUpdate(base_url="http://10.0.0.9/v1/"))
    assert agents.state.agents["helper"].base_url == "http://10.0.0.9/v1"


def test_renaming_to_a_taken_name_names_the_name_asked_for(agents: Agents) -> None:
    with pytest.raises(Conflict) as caught:
        agents.service.update(ADMIN, "helper", AgentUpdate(name="PLANNER"))
    assert (caught.value.code, caught.value.details) == ("agent_name_taken", {"name": "PLANNER"})


def test_a_duplicate_keeps_the_connection_but_never_the_key_or_the_last_test(
    agents: Agents,
) -> None:
    agents.state.agents["helper"] = agents.state.agents["helper"].__replace__(
        last_test_status="connected", last_tested_at=CREATED, supports_json_schema=1
    )
    entry = agents.service.duplicate(ADMIN, "helper", AgentDuplicate())
    copy = agents.state.agents["new-1"]
    original = agents.state.agents["helper"]
    assert (entry["name"], copy.base_url, copy.model, copy.role_template_id) == (
        "Helper (copy)",
        original.base_url,
        "m1",
        "board-role",
    )
    assert (copy.api_key_ciphertext, copy.api_key_hint, copy.last_test_status) == (None, None, None)
    assert (copy.supports_json_schema, entry["supports_json_schema"]) == (0, False)
    assert (copy.created_at, copy.updated_at) == (NOW, NOW)
    assert agents.service.duplicate(ADMIN, "helper", AgentDuplicate(name=" Two "))["name"] == "Two"
    with pytest.raises(Conflict) as caught:
        agents.service.duplicate(ADMIN, "helper", AgentDuplicate(name="helper (COPY)"))
    assert caught.value.details == {"name": "helper (COPY)"}


def test_a_deleted_agent_leaves_every_board_that_selected_it(agents: Agents) -> None:
    agents.service.set_board_agents("board-1", ["helper"])
    agents.service.delete(ADMIN, "helper")
    assert "helper" not in agents.state.agents
    assert agents.service.agent_ids("board-1") == []
    with pytest.raises(NotFound):
        agents.service.delete(ADMIN, "helper")


def test_each_command_asks_for_its_scope(agents: Agents) -> None:
    with pytest.raises(Forbidden):
        agents.service.create(READER, create())
    with pytest.raises(Forbidden):
        agents.service.update(READER, "helper", AgentUpdate(name="x"))
    with pytest.raises(Forbidden):
        agents.service.duplicate(READER, "helper", AgentDuplicate())
    with pytest.raises(Forbidden):
        agents.service.test(READER, "helper", AgentTestRequest())
    with pytest.raises(Forbidden):
        agents.service.probe(READER, AgentTestRequest(base_url="http://10.0.0.5/v1"))
    with pytest.raises(Forbidden):
        agents.service.delete(WRITER, "helper")
    assert (agents.store.commits, agents.endpoints.calls) == (0, [])


# --- boards --------------------------------------------------------------------------------------


def test_a_board_takes_existing_board_profiles_only(agents: Agents) -> None:
    with pytest.raises(NotFound) as missing:
        agents.service.validate_ids(["helper", "nothing"])
    assert missing.value.code == "agent_not_found"
    with pytest.raises(ValidationFailure) as organisation:
        agents.service.validate_ids(["planner"])
    assert (organisation.value.code, organisation.value.details) == (
        "agent_scope_organisation",
        {"agent_id": "planner"},
    )
    # A template that is gone leaves a board profile.
    agents.state.agents["planner"] = agents.state.agents["planner"].__replace__(
        role_template_id="gone"
    )
    agents.service.validate_ids(["planner", "override"])


def test_a_selection_replaces_the_previous_one_once_per_agent(agents: Agents) -> None:
    agents.service.set_board_agents("board-1", ["override"])
    agents.service.set_board_agents("board-1", ["helper", "override", "helper"])
    agents.service.set_board_agents("board-2", ["helper"])
    assert agents.service.agent_ids("board-1") == ["helper", "override"]
    assert agents.service.agent_ids_for_boards() == {
        "board-1": ["helper", "override"],
        "board-2": ["helper"],
    }
    assert {link.created_at for link in agents.state.agent_links.values()} == {NOW}


def test_a_refused_selection_keeps_the_previous_one(agents: Agents) -> None:
    agents.service.set_board_agents("board-1", ["helper"])
    with pytest.raises(ValidationFailure):
        agents.service.set_board_agents("board-1", ["override", "planner"])
    assert agents.service.agent_ids("board-1") == ["helper"]


def test_a_selection_lists_in_the_order_it_was_made_then_by_id(agents: Agents) -> None:
    agents.service.set_board_agents("board-1", ["override", "helper"])
    # One selection is written in one second: SQL orders it by created_at, then agent id.
    assert agents.service.agent_ids("board-1") == ["helper", "override"]


# --- secret rotation -----------------------------------------------------------------------------


def test_keys_sealed_with_the_previous_secret_move_to_the_current_one(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    previous = settings.model_copy(update={"secret_key": OTHER_SECRET})
    rotated = settings.model_copy(update={"previous_secret_key": OTHER_SECRET})
    agents = make_agents(rotated)
    current_ciphertext = agents.state.agents["helper"].api_key_ciphertext
    agents.state.agents["planner"] = agents.state.agents["planner"].__replace__(
        api_key_ciphertext=seal_secret(previous, "sk-old-1111")
    )
    agents.state.agents["override"] = agents.state.agents["override"].__replace__(
        api_key_ciphertext="not-a-sealed-value"
    )
    with caplog.at_level(logging.WARNING, logger="tralala.agents"):
        assert agents.service.reseal_credentials() == 1
    moved = agents.state.agents["planner"].api_key_ciphertext or ""
    assert open_secret_state(rotated, moved) == ("sk-old-1111", True)
    assert agents.state.agents["helper"].api_key_ciphertext == current_ciphertext
    assert agents.state.agents["override"].api_key_ciphertext == "not-a-sealed-value"
    assert "agent override has a credential that no configured secret can open" in caplog.text
    assert agents.store.commits == 1
    assert agents.service.reseal_credentials() == 0
    assert agents.store.commits == 1


# --- connection tests ----------------------------------------------------------------------------


def test_testing_a_stored_agent_uses_its_key_model_and_timeout_and_records_the_outcome(
    agents: Agents,
) -> None:
    long_message = "x" * 600
    agents.endpoints.models = {
        "ok": True,
        "status": "connected",
        "message": long_message,
        "latency_ms": 5,
        "models": ["m1"],
    }
    result = agents.service.test(ADMIN, "helper", AgentTestRequest())
    assert agents.endpoints.calls == [
        ("models", "http://10.0.0.5:8080/v1", KEY, 12.0),
        ("completion m1", "http://10.0.0.5:8080/v1", KEY, 12.0),
    ]
    assert result.get("completion") == COMPLETED
    assert result["message"] == f"{long_message}; model m1 answered in 7 ms"
    row = agents.state.agents["helper"]
    assert (row.last_test_status, row.last_tested_at) == ("connected", NOW)
    assert row.last_test_message == result["message"][:500]
    assert row.updated_at == CREATED
    # The model answered the call that asked for a JSON schema, so generations will send one.
    assert (result["supports_json_schema"], row.supports_json_schema) == (True, 1)
    assert agents.service.get("helper")["supports_json_schema"] is True


@pytest.mark.parametrize(
    "completion",
    [
        {**COMPLETED, "supports_json_schema": False},
        {
            "ok": False,
            "status": "http_404",
            "message": "The model call was refused: no such model",
            "latency_ms": 6,
            "supports_json_schema": True,
        },
    ],
    ids=["refused the schema", "model call failed"],
)
def test_every_test_records_afresh_whether_the_provider_takes_a_json_schema(
    agents: Agents, completion: CompletionProbe
) -> None:
    agents.state.agents["helper"] = agents.state.agents["helper"].__replace__(
        supports_json_schema=1
    )
    agents.endpoints.completion = completion
    result = agents.service.test(ADMIN, "helper", AgentTestRequest())
    assert result["supports_json_schema"] is False
    assert agents.state.agents["helper"].supports_json_schema == 0


def test_a_test_without_a_model_call_records_no_json_schema(agents: Agents) -> None:
    agents.state.agents["override"] = agents.state.agents["override"].__replace__(
        supports_json_schema=1
    )
    result = agents.service.test(ADMIN, "override", AgentTestRequest())
    assert ("completion" not in result, result["supports_json_schema"]) == (True, False)
    assert agents.state.agents["override"].supports_json_schema == 0


def test_a_test_may_go_without_the_stored_key_or_with_another(agents: Agents) -> None:
    agents.service.test(ADMIN, "helper", AgentTestRequest(no_api_key=True, api_key="sk-other"))
    agents.service.test(ADMIN, "helper", AgentTestRequest(api_key="sk-other", model="m2"))
    assert [(call[0], call[2]) for call in agents.endpoints.calls] == [
        ("models", None),
        ("completion m1", None),
        ("models", "sk-other"),
        ("completion m2", "sk-other"),
    ]


def test_a_key_no_secret_opens_is_tested_without_a_key(agents: Agents) -> None:
    agents.state.agents["helper"] = agents.state.agents["helper"].__replace__(
        api_key_ciphertext="not-a-sealed-value"
    )
    agents.service.test(ADMIN, "helper", AgentTestRequest())
    assert agents.endpoints.calls[0][2] is None


def test_a_model_that_does_not_answer_fails_the_test_but_keeps_the_model_list(
    agents: Agents,
) -> None:
    agents.endpoints.completion = {
        "ok": False,
        "status": "http_404",
        "message": "The model call was refused: no such model",
        "latency_ms": 6,
        "supports_json_schema": False,
    }
    result = agents.service.probe(
        ADMIN, AgentTestRequest(base_url="http://10.0.0.5/v1", model="missing")
    )
    assert result == {
        "ok": False,
        "status": "http_404",
        "message": "Endpoint answers, but the model call failed. The model call was refused: no "
        "such model",
        "latency_ms": 5,
        "models": ["m1", "m2"],
        "supports_json_schema": False,
        "completion": agents.endpoints.completion,
    }


def test_without_a_model_or_a_list_no_model_call_is_made(agents: Agents) -> None:
    unsaved = agents.service.probe(ADMIN, AgentTestRequest(base_url="http://10.0.0.5/v1"))
    unsaved_outcome = {**CONNECTED, "supports_json_schema": False}
    assert (unsaved, len(agents.endpoints.calls)) == (unsaved_outcome, 1)
    agents.endpoints.models = {
        "ok": False,
        "status": "unauthorized",
        "message": "Endpoint rejected the credentials (HTTP 401)",
        "latency_ms": 4,
        "models": [],
    }
    refused = agents.service.probe(
        ADMIN, AgentTestRequest(base_url="http://10.0.0.5/v1", model="m1")
    )
    assert ("completion" not in refused, len(agents.endpoints.calls)) == (True, 2)


def test_an_a2a_agent_is_probed_for_its_card_and_never_for_a_model(agents: Agents) -> None:
    result = agents.service.test(ADMIN, "override", AgentTestRequest(model="m1"))
    assert agents.endpoints.calls == [("a2a", "http://10.0.0.6:9000", None, 30.0)]
    assert "completion" not in result


def test_a_probe_needs_an_endpoint_the_rule_allows(agents: Agents) -> None:
    with pytest.raises(ValidationFailure) as missing:
        agents.service.probe(ADMIN, AgentTestRequest())
    assert missing.value.details == {"field": "base_url"}
    with pytest.raises(ValidationFailure):
        agents.service.probe(ADMIN, AgentTestRequest(base_url="http://169.254.169.254/"))
    assert agents.endpoints.calls == []


def test_a_probe_that_raises_is_logged_and_raised_and_records_nothing(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    agents = make_agents(settings, Endpoints(failure=RuntimeError("boom")))
    with (
        caplog.at_level(logging.INFO, logger="tralala.agents"),
        pytest.raises(RuntimeError, match="boom"),
    ):
        agents.service.test(ADMIN, "helper", AgentTestRequest())
    started, failed = events(caplog.records)
    assert started["event"] == "agent_probe_started"
    assert (failed["event"], failed["reason"]) == ("agent_probe_failed", "RuntimeError")
    assert agents.state.agents["helper"].last_test_status is None


def test_the_probe_log_never_carries_the_key(
    agents: Agents, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="tralala.agents"):
        agents.service.test(ADMIN, "helper", AgentTestRequest())
        agents.service.probe(
            ADMIN, AgentTestRequest(base_url="http://10.0.0.5/v1", api_key="sk-unsaved-7777")
        )
    written = lines(caplog.records)
    assert len(written) == 4
    assert KEY not in json.dumps(written)
    assert "sk-unsaved-7777" not in json.dumps(written)
    started = [line for line in written if line["event"] == "agent_probe_started"]
    assert [line["has_api_key"] for line in started] == [True, True]
