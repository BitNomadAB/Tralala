from __future__ import annotations

from typing import Any

import pytest
from conftest import Api

from app.core.context import ActorContext
from app.core.errors import Forbidden
from app.core.secrets import open_secret
from app.services import connections


def _roles(api: Api) -> list[dict[str, Any]]:
    return api.data(api.get("/api/v1/role-templates"))


def _role_by_key(api: Api, key: str) -> dict[str, Any]:
    return next(role for role in _roles(api) if role["builtin_key"] == key)


def _agent(api: Api, **overrides: Any) -> dict[str, Any]:
    role = _role_by_key(api, "qa_engineer")
    payload: dict[str, Any] = {
        "name": overrides.pop("name", "QA Bot"),
        "connection_type": "openai_compatible",
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "local-model",
        "role_template_id": role["id"],
        **overrides,
    }
    return api.data(api.post("/api/v1/agents", json=payload))


def test_builtin_role_templates_are_seeded(api: Api) -> None:
    roles = _roles(api)
    keys = {role["builtin_key"] for role in roles if role["built_in"]}
    assert {
        "lead_developer",
        "project_manager",
        "product_owner",
        "backend_developer",
        "frontend_developer",
        "qa_engineer",
        "security_engineer",
        "ux_designer",
        "customer",
        "analytics_agent",
    } <= keys
    assert all(role["system_prompt"].strip() for role in roles)
    assert all(role["customized"] is False for role in roles)


def test_role_template_crud_and_duplicate(api: Api) -> None:
    created = api.data(
        api.post(
            "/api/v1/role-templates",
            json={
                "name": "Data Steward",
                "description": "Schema and data quality",
                "system_prompt": "You guard the data model.",
            },
        )
    )
    assert created["built_in"] is False
    assert created["customized"] is False

    updated = api.data(
        api.patch(
            f"/api/v1/role-templates/{created['id']}",
            json={"system_prompt": "You guard the data model and migrations."},
        )
    )
    assert "migrations" in updated["system_prompt"]
    assert updated["customized"] is True

    duplicated = api.data(
        api.post(f"/api/v1/role-templates/{created['id']}/duplicate", json={})
    )
    assert duplicated["name"] == "Data Steward (copy)"
    assert duplicated["built_in"] is False
    assert duplicated["agent_count"] == 0

    api.data(api.delete(f"/api/v1/role-templates/{duplicated['id']}"))
    assert api.data(api.get(f"/api/v1/role-templates/{created['id']}"))["id"] == created["id"]


def test_builtin_role_cannot_be_deleted_but_can_be_restored(api: Api) -> None:
    role = _role_by_key(api, "security_engineer")
    delete = api.delete(f"/api/v1/role-templates/{role['id']}")
    assert delete.status_code == 409
    assert delete.json()["error"]["code"] == "role_template_builtin"

    api.data(
        api.patch(
            f"/api/v1/role-templates/{role['id']}",
            json={"system_prompt": "Shortened prompt"},
        )
    )
    restored = api.data(
        api.post(f"/api/v1/role-templates/{role['id']}/restore-defaults", json={})
    )
    assert restored["customized"] is False
    assert "Threat-model" in restored["system_prompt"]


def test_role_template_names_are_unique(api: Api) -> None:
    response = api.post(
        "/api/v1/role-templates",
        json={"name": "qa engineer", "system_prompt": "Duplicate name"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "role_template_name_taken"


def test_agent_hides_credentials_and_stores_them_encrypted(api: Api, settings: Any) -> None:
    agent = _agent(api, api_key="sk-secret-value-1234")
    assert agent["has_api_key"] is True
    assert agent["api_key_hint"] == "\u2022\u2022\u2022\u2022" + "1234"
    assert "api_key" not in agent
    listing = api.data(api.get("/api/v1/agents"))
    assert "sk-secret-value" not in str(listing)

    services = api.client.app.state.services
    row = services.registry.read_one("SELECT * FROM agents WHERE id = :id", {"id": agent["id"]})
    assert "sk-secret-value" not in (row["api_key_ciphertext"] or "")
    assert open_secret(settings, row["api_key_ciphertext"]) == "sk-secret-value-1234"

    cleared = api.data(api.patch(f"/api/v1/agents/{agent['id']}", json={"clear_api_key": True}))
    assert cleared["has_api_key"] is False


def test_agent_requires_a_role_or_override(api: Api) -> None:
    response = api.post(
        "/api/v1/agents",
        json={"name": "No Role", "connection_type": "openai_compatible", "base_url": "http://x.test"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",
        "http://user:pass@example.com/v1",
        "http://metadata.google.internal/v1",
    ],
)
def test_agent_endpoint_validation_rejects_unsafe_targets(api: Api, url: str) -> None:
    role = _role_by_key(api, "qa_engineer")
    response = api.post(
        "/api/v1/agents",
        json={
            "name": f"Bad {hostname_of(url)}",
            "connection_type": "openai_compatible",
            "base_url": url,
            "role_template_id": role["id"],
        },
    )
    assert response.status_code == 422


def hostname_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0][:20]


def test_role_snapshot_survives_later_template_edits(api: Api) -> None:
    services = api.client.app.state.services
    role = _role_by_key(api, "backend_developer")
    agent = _agent(api, name="Backend Bot", role_template_id=role["id"])

    before = services.agent.role_snapshot(agent["id"])
    assert before["role_template_id"] == role["id"]
    assert before["role_source"] == "template"
    assert before["system_prompt"] == role["system_prompt"]

    api.data(
        api.patch(
            f"/api/v1/role-templates/{role['id']}",
            json={"system_prompt": "A completely rewritten role."},
        )
    )
    after = services.agent.role_snapshot(agent["id"])
    assert after["system_prompt"] == "A completely rewritten role."
    assert after["system_prompt_sha256"] != before["system_prompt_sha256"]
    assert before["system_prompt"] == role["system_prompt"]
    assert before["role_template_updated_at"] == role["updated_at"]


def test_agent_override_takes_precedence_and_survives_template_change(api: Api) -> None:
    services = api.client.app.state.services
    role = _role_by_key(api, "customer")
    agent = _agent(
        api,
        name="Customer Bot",
        role_template_id=role["id"],
        role_prompt_override="You are a skeptical customer.",
    )
    effective = services.agent.effective_role(agent["id"])
    assert effective["role_source"] == "override"
    assert effective["system_prompt"] == "You are a skeptical customer."
    assert effective["template_system_prompt"] == role["system_prompt"]

    snapshot = services.agent.role_snapshot(agent["id"])
    api.data(
        api.patch(
            f"/api/v1/role-templates/{role['id']}",
            json={"system_prompt": "Template changed later."},
        )
    )
    assert snapshot["system_prompt"] == "You are a skeptical customer."


def test_deleting_custom_role_keeps_agents_and_discussion_history(api: Api) -> None:
    services = api.client.app.state.services
    custom = api.data(
        api.post(
            "/api/v1/role-templates",
            json={"name": "Temp Role", "system_prompt": "Temporary role."},
        )
    )
    agent = _agent(api, name="Temp Agent", role_template_id=custom["id"])
    assert agent["role_template_name"] == "Temp Role"

    api.data(api.delete(f"/api/v1/role-templates/{custom['id']}"))
    refreshed = api.data(api.get(f"/api/v1/agents/{agent['id']}"))
    assert refreshed["role_template_id"] is None
    with pytest.raises(Exception) as excinfo:
        services.agent.effective_role(agent["id"])
    assert getattr(excinfo.value, "status_code", None) == 422

    api.data(
        api.patch(
            f"/api/v1/agents/{agent['id']}",
            json={"role_prompt_override": "Recovered role prompt."},
        )
    )
    assert services.agent.effective_role(agent["id"])["role_source"] == "override"


def test_agent_connection_test_records_result(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent(api, name="Probe Bot", api_key="sk-probe")

    def fake_probe(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
        assert api_key == "sk-probe"
        return {
            "ok": True,
            "status": "connected",
            "message": "Connected; 1 model(s) reported",
            "latency_ms": 12,
            "models": ["local-model"],
        }

    def fake_completion(
        base_url: str, *, model: str, api_key: str | None, timeout: float
    ) -> dict[str, Any]:
        assert model == "local-model"
        return {
            "ok": True,
            "status": "completed",
            "message": f"Model {model} answered: ok",
            "latency_ms": 40,
        }

    monkeypatch.setattr(connections, "probe_openai_compatible", fake_probe)
    monkeypatch.setattr(connections, "probe_completion", fake_completion)
    result = api.data(api.post(f"/api/v1/agents/{agent['id']}/test", json={}))
    assert result["ok"] is True
    assert result["models"] == ["local-model"]
    assert result["completion"]["status"] == "completed"
    assert "local-model answered" in result["message"]

    refreshed = api.data(api.get(f"/api/v1/agents/{agent['id']}"))
    assert refreshed["last_test_status"] == "connected"
    assert refreshed["last_tested_at"] is not None


def test_a_green_model_list_does_not_hide_a_refused_model_call(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listing models answers; the model call is what a generation actually does."""
    agent = _agent(api, name="Half Bot")

    def fake_probe(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "connected",
            "message": "Connected; 2 model(s) reported",
            "latency_ms": 9,
            "models": ["one", "two"],
        }

    def refused(
        base_url: str, *, model: str, api_key: str | None, timeout: float
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "http_400",
            "message": "The model call was refused: HTTP 400: Model Not Exist",
            "latency_ms": 11,
        }

    monkeypatch.setattr(connections, "probe_openai_compatible", fake_probe)
    monkeypatch.setattr(connections, "probe_completion", refused)
    result = api.data(api.post(f"/api/v1/agents/{agent['id']}/test", json={}))

    assert result["ok"] is False
    assert result["status"] == "http_400"
    assert "Model Not Exist" in result["message"]
    # The model list still comes back, so the form can offer what the endpoint does know.
    assert result["models"] == ["one", "two"]

    refreshed = api.data(api.get(f"/api/v1/agents/{agent['id']}"))
    assert refreshed["last_test_status"] == "http_400"


def test_an_a2a_agent_is_not_probed_with_a_chat_completion(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    role = _role_by_key(api, "qa_engineer")
    agent = api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": "Remote",
                "connection_type": "a2a",
                "base_url": "http://127.0.0.1:9001",
                "model": "ignored",
                "role_template_id": role["id"],
            },
        )
    )

    def fake_card(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "connected",
            "message": "Agent card found for Remote",
            "latency_ms": 5,
            "models": [],
        }

    def unexpected(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("an A2A agent must not be sent a chat completion")

    monkeypatch.setattr(connections, "probe_a2a", fake_card)
    monkeypatch.setattr(connections, "probe_completion", unexpected)
    result = api.data(api.post(f"/api/v1/agents/{agent['id']}/test", json={}))

    assert result["ok"] is True
    assert result["completion"] is None


def test_agent_duplicate_does_not_clone_credentials(api: Api) -> None:
    agent = _agent(api, name="Original", api_key="sk-original")
    copy = api.data(api.post(f"/api/v1/agents/{agent['id']}/duplicate", json={}))
    assert copy["name"] == "Original (copy)"
    assert copy["has_api_key"] is False
    assert copy["role_template_id"] == agent["role_template_id"]


def test_agent_requires_agent_scope(api: Api) -> None:
    services = api.client.app.state.services
    actor = ActorContext(
        actor_id="token-actor",
        actor_type="agent",
        actor_name="agent-token",
        scopes=frozenset({"boards:read"}),
    )
    with pytest.raises(Forbidden):
        services.agent.test(
            actor,
            "anything",
            __import__("app.schemas.agents", fromlist=["AgentTestRequest"]).AgentTestRequest(),
        )


def test_agent_directory_returns_only_identity_and_role(api: Api) -> None:
    enabled = _agent(api, name="Directory Bot", api_key="sk-directory-secret")
    disabled = _agent(api, name="Hidden Bot", enabled=False)
    directory = api.data(api.get("/api/v1/agents/directory"))

    entries = {entry["id"]: entry for entry in directory}
    assert enabled["id"] in entries
    assert disabled["id"] not in entries
    assert set(entries[enabled["id"]]) == {
        "id",
        "name",
        "role_template_id",
        "role_template_name",
        "role_template_scope",
    }
    assert entries[enabled["id"]]["name"] == "Directory Bot"
    assert entries[enabled["id"]]["role_template_name"] == "QA Engineer"
    assert entries[enabled["id"]]["role_template_scope"] == "board"
    body = api.get("/api/v1/agents/directory").text
    assert "sk-directory" not in body
    assert "127.0.0.1:8080" not in body


def test_agent_endpoints_require_auth(client: Any) -> None:
    assert client.get("/api/v1/agents").status_code == 401
    assert client.get("/api/v1/agents/directory").status_code == 401
    assert client.get("/api/v1/role-templates").status_code == 401
