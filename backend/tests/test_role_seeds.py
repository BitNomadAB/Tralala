"""Role seeds: one JSON file, validated, with board and organisation profiles."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from conftest import Api
from sqlalchemy import text

from app.services import role_defaults, runtime


def test_the_seed_file_defines_every_builtin_role() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    keys = [role["key"] for role in document["roles"]]
    assert keys == list(role_defaults.BUILTIN_ROLE_KEYS)
    assert len(keys) == len(set(keys))
    assert {"coordinator", "architect"} <= set(keys)


def test_the_seed_file_is_the_only_source_of_the_prompts() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    preamble = document["discussion_preamble"]
    seeded = {role["key"]: role for role in document["roles"]}
    for role in role_defaults.BUILTIN_ROLES:
        expected = seeded[role["key"]]["prompt"].replace("{{discussion}}", preamble).strip()
        assert role["prompt"] == expected
    assert "{{discussion}}" not in "".join(role["prompt"] for role in role_defaults.BUILTIN_ROLES)


def test_board_and_organisation_profiles_are_separated() -> None:
    assert {role["key"] for role in role_defaults.ORGANISATION_ROLES} == {
        "coordinator",
        "architect",
    }
    assert all(role["scope"] == "board" for role in role_defaults.BOARD_ROLES)
    assert len(role_defaults.BOARD_ROLES) + len(role_defaults.ORGANISATION_ROLES) == len(
        role_defaults.BUILTIN_ROLES
    )


def test_the_organisation_profiles_describe_their_own_job() -> None:
    prompts = {role["key"]: role["prompt"] for role in role_defaults.ORGANISATION_ROLES}
    assert "across every board" in prompts["coordinator"]
    assert "recommend" in prompts["coordinator"].lower()
    assert "every repository" in prompts["architect"]
    assert "read-only token" in prompts["architect"]
    for prompt in prompts.values():
        assert "data to analyse" in prompt


def test_a_broken_seed_fails_instead_of_seeding_nothing(tmp_path: Any) -> None:
    broken = tmp_path / "roles.json"
    broken.write_text(json.dumps({"roles": [{"key": "x", "name": "X"}]}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        role_defaults._load(broken)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        json.dumps(
            {
                "roles": [
                    {"key": "x", "name": "X", "prompt": "p"},
                    {"key": "x", "name": "X again", "prompt": "p"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError):
        role_defaults._load(duplicate)


def test_the_registry_seeds_both_new_profiles(api: Api) -> None:
    roles = api.data(api.get("/api/v1/role-templates"))
    by_key = {role["builtin_key"]: role for role in roles if role["builtin_key"]}
    assert by_key["coordinator"]["scope"] == "organisation"
    assert by_key["architect"]["scope"] == "organisation"
    assert by_key["coordinator"]["name"] == "Coordinator"
    assert by_key["architect"]["name"] == "Architect"
    assert by_key["analytics_agent"]["scope"] == "board"
    assert by_key["analytics_agent"]["built_in"] is True


def _agent_with_role(api: Api, name: str, role_key: str) -> dict[str, Any]:
    roles = api.data(api.get("/api/v1/role-templates"))
    role = next(entry for entry in roles if entry["builtin_key"] == role_key)
    return api.data(
        api.post(
            "/api/v1/agents",
            json={
                "name": name,
                "connection_type": "openai_compatible",
                "base_url": "http://127.0.0.1:8099/v1",
                "role_template_id": role["id"],
            },
        )
    )


def test_an_organisation_profile_is_not_a_board_agent(api: Api) -> None:
    coordinator = _agent_with_role(api, "coordinator agent", "coordinator")
    assert coordinator["role_template_scope"] == "organisation"

    response = api.post(
        "/api/v1/boards", json={"name": "Org board", "agent_ids": [coordinator["id"]]}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "agent_scope_organisation"
    assert api.data(api.get("/api/v1/boards")) == []

    board = api.data(api.post("/api/v1/boards", json={"name": "Kept board"}))
    rejected = api.patch(
        f"/api/v1/boards/{board['id']}", json={"agent_ids": [coordinator["id"]]}
    )
    assert rejected.status_code == 422
    assert api.data(api.get(f"/api/v1/boards/{board['id']}"))["agent_ids"] == []


def test_a_board_profile_stays_selectable(api: Api) -> None:
    board_agent = _agent_with_role(api, "analyst agent", "analytics_agent")
    board = api.data(
        api.post("/api/v1/boards", json={"name": "Board", "agent_ids": [board_agent["id"]]})
    )
    assert board["agent_ids"] == [board_agent["id"]]


def test_duplicating_an_organisation_profile_keeps_its_scope(api: Api) -> None:
    roles = api.data(api.get("/api/v1/role-templates"))
    architect = next(entry for entry in roles if entry["builtin_key"] == "architect")
    copy = api.data(
        api.post(f"/api/v1/role-templates/{architect['id']}/duplicate", json={})
    )
    assert copy["scope"] == "organisation"
    assert copy["built_in"] is False


def _loop_base(board: dict[str, Any], loop: dict[str, Any]) -> str:
    return f"/api/v1/boards/{board['id']}/loops/{loop['id']}"


def test_generation_refuses_an_organisation_profile(
    api: Api, board: dict[str, Any], loop: dict[str, Any]
) -> None:
    coordinator = _agent_with_role(api, "coordinator agent", "coordinator")
    api.data(api.put(f"{_loop_base(board, loop)}/documents/info", json={"content": "Intent"}))

    response = api.post(
        f"{_loop_base(board, loop)}/generation-runs",
        json={"purpose": "analysis", "agent_id": coordinator["id"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "agent_scope_organisation"


def test_the_default_agent_skips_an_organisation_profile(
    api: Api, board: dict[str, Any], loop: dict[str, Any], monkeypatch: Any
) -> None:
    _agent_with_role(api, "aaa coordinator", "coordinator")
    worker = _agent_with_role(api, "zzz analyst", "analytics_agent")
    api.data(api.put(f"{_loop_base(board, loop)}/documents/info", json={"content": "Intent"}))
    used: dict[str, Any] = {}

    def fake_call(settings: Any, agent_row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        used["agent"] = agent_row
        return {
            "ok": True,
            "error": None,
            "text": (
                '{"schema_version":1,"outcome":"x","scope":[],"findings":[],"assumptions":[],'
                '"open_questions":[],"options":[],"recommendation":"x","verification":[],'
                '"sources":[],"repository_revision":""}'
            ),
            "model": "m",
            "usage": {},
        }

    monkeypatch.setattr(runtime, "call_completion", fake_call)
    started = api.data(
        api.post(f"{_loop_base(board, loop)}/generation-runs", json={"purpose": "analysis"})
    )
    for _ in range(100):
        run = api.data(api.get(f"{_loop_base(board, loop)}/generation-runs/{started['id']}"))
        if run["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.05)
    assert used["agent"]["id"] == worker["id"]


def test_the_factory_prompts_never_name_the_product() -> None:
    """A profile refers to the Loop or discussion it is given, never to a fixed product name."""
    for role in role_defaults.BUILTIN_ROLES:
        assert "Tralala" not in role["prompt"], role["key"]
    analytics = next(r for r in role_defaults.BUILTIN_ROLES if r["key"] == "analytics_agent")
    assert "the Loop you are asked about" in analytics["prompt"]
    assert "given to you with the request" in analytics["prompt"]


def test_the_discussion_preamble_points_at_the_given_context() -> None:
    document = json.loads(role_defaults.SEED_PATH.read_text(encoding="utf-8"))
    preamble = document["discussion_preamble"]
    assert "Tralala" not in preamble
    assert "The message you receive names the ticket" in preamble
    assert "never guess an identity" in preamble


def test_an_untouched_builtin_follows_the_factory_text(api: Api) -> None:
    """A prompt rewrite has to reach an installation that never edited the role."""
    services = api.client.app.state.services
    roles = api.data(api.get("/api/v1/role-templates"))
    builtin = next(entry for entry in roles if entry["builtin_key"] == "analytics_agent")
    with services.registry.connect() as conn:
        conn.execute(
            text(
                "UPDATE role_templates SET system_prompt = 'Old factory text',"
                " default_system_prompt = 'Old factory text' WHERE id = :id"
            ),
            {"id": builtin["id"]},
        )

    services.role_templates.seed_defaults()

    refreshed = api.data(api.get(f"/api/v1/role-templates/{builtin['id']}"))
    assert refreshed["system_prompt"] != "Old factory text"
    assert "the Loop you are asked about" in refreshed["system_prompt"]
    assert refreshed["customized"] is False


def test_a_customized_builtin_keeps_its_prompt_but_gains_the_new_default(api: Api) -> None:
    services = api.client.app.state.services
    roles = api.data(api.get("/api/v1/role-templates"))
    builtin = next(entry for entry in roles if entry["builtin_key"] == "qa_engineer")
    api.data(
        api.patch(
            f"/api/v1/role-templates/{builtin['id']}",
            json={"system_prompt": "Our own QA voice, edited by a person."},
        )
    )

    services.role_templates.seed_defaults()

    refreshed = api.data(api.get(f"/api/v1/role-templates/{builtin['id']}"))
    assert refreshed["system_prompt"] == "Our own QA voice, edited by a person."
    assert refreshed["customized"] is True

    restored = api.data(
        api.post(f"/api/v1/role-templates/{builtin['id']}/restore-defaults")
    )
    assert restored["system_prompt"] != "Our own QA voice, edited by a person."
    assert "Tralala" not in restored["system_prompt"]
