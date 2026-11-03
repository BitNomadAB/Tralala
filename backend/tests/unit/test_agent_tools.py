"""The worker catalogue as data, and `/llms.txt` as the text generated from it."""

from __future__ import annotations

import re

import pytest

from app.api.mcp import render_bootstrap
from app.core.config import Settings
from app.core.context import MEMBER_TOKEN_SCOPES, SCOPES, ActorContext
from app.services.agent_tools import AgentTool, describe_scope, missing_scopes, tool_catalog

CATALOGUE = tool_catalog()


def _token(*scopes: str) -> ActorContext:
    return ActorContext(
        actor_id="agent-1", actor_type="agent", actor_name="worker", scopes=frozenset(scopes)
    )


def _visible(actor: ActorContext) -> list[str]:
    return [tool.name for tool in CATALOGUE.values() if not missing_scopes(tool, actor)]


def test_the_catalogue_is_built_the_same_every_time() -> None:
    again = tool_catalog()
    assert list(again) == list(CATALOGUE)
    assert [tool.input_schema for tool in again.values()] == [
        tool.input_schema for tool in CATALOGUE.values()
    ]


@pytest.mark.parametrize("tool", CATALOGUE.values(), ids=list(CATALOGUE))
def test_every_tool_is_a_closed_contract(tool: AgentTool) -> None:
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) <= set(schema["properties"])
    assert all(spec.get("type") for spec in schema["properties"].values())
    assert tool.description.strip()
    assert callable(tool.handler)


@pytest.mark.parametrize("tool", CATALOGUE.values(), ids=list(CATALOGUE))
def test_every_tool_needs_a_known_working_scope(tool: AgentTool) -> None:
    assert tool.scopes
    assert set(tool.scopes) <= set(SCOPES)
    assert "loops:review" not in tool.scopes
    assert not [scope for scope in tool.scopes if scope.endswith(":admin")]


def test_a_token_sees_only_the_tools_its_scopes_cover() -> None:
    assert _visible(_token()) == []
    assert _visible(_token("boards:read")) == ["list_boards"]
    assert _visible(_token("loops:read")) == ["read_loop", "read_notes"]
    assert _visible(_token("boards:read", "loops:read")) == [
        "list_boards",
        "read_board",
        "read_loop",
        "read_notes",
    ]
    assert _visible(_token("cards:read")) == ["read_ticket", "search_tickets"]
    assert _visible(_token(*MEMBER_TOKEN_SCOPES)) == list(CATALOGUE)


def test_a_refusal_names_exactly_the_missing_scopes() -> None:
    read_board = CATALOGUE["read_board"]
    assert missing_scopes(read_board, _token()) == ("boards:read", "loops:read")
    assert missing_scopes(read_board, _token("boards:read")) == ("loops:read",)
    assert missing_scopes(read_board, _token("boards:read", "loops:read")) == ()
    assert describe_scope(read_board) == "Requires `boards:read`, `loops:read`."


# --- /llms.txt ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bootstrap(settings: Settings) -> str:
    return render_bootstrap(settings)


def test_the_bootstrap_marks_each_argument_required_or_optional(bootstrap: str) -> None:
    for tool in CATALOGUE.values():
        section = bootstrap.split(f"### {tool.name} (", 1)[1].split("\n### ", 1)[0]
        for name in tool.input_schema["properties"]:
            marker = "required" if name in tool.input_schema["required"] else "optional"
            assert f"- `{name}` ({marker}):" in section, (tool.name, name)


def test_the_bootstrap_is_a_contract_not_a_data_dump(settings: Settings, bootstrap: str) -> None:
    assert settings.secret_key and settings.secret_key not in bootstrap
    assert str(settings.data_dir) not in bootstrap
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", bootstrap)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", bootstrap)
    assert "127.0.0.1" not in bootstrap and "localhost" not in bootstrap
    assert "Authorization: Bearer <token>" in bootstrap


def test_the_bootstrap_states_the_limits_it_was_given(settings: Settings, bootstrap: str) -> None:
    assert f"default {settings.rate_limit_per_minute}/minute" in bootstrap
    assert f"capped at {settings.max_request_bytes} bytes" in bootstrap
    assert render_bootstrap(settings) == bootstrap
