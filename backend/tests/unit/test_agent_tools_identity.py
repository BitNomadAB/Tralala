"""``whoami`` on the fakes: the real AuthService on the registry fakes, handed to the tool as the
attribute ``IdentityReading`` declares; the key, the tools and the gaps it reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden
from app.services.agent_tools import tool_catalog, whoami
from app.services.agent_tools_identity import HUMAN_DECISIONS
from app.services.auth import AuthService
from tests.unit.fakes.data_files import FakeBootstrapPasswordFile
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    credential_row,
)

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
AGENT = "agent-1"
SCOPES = frozenset({"boards:read", "cards:read", "loops:read"})


@dataclass(frozen=True, slots=True)
class IdentityWorld:
    """What ``whoami`` declares it uses of the composition root."""

    auth: AuthService


def identity_world(settings: Settings) -> IdentityWorld:
    """Ada issued the key ``laptop`` (expiring in three days) and ``forever`` (no expiry) to her
    agent."""
    state = RegistryState()
    state.actors = {
        "user-1": actor_row("user-1", name="Ada"),
        AGENT: actor_row(AGENT, type_="agent", name="Ada's laptop"),
    }
    state.credentials = {
        "laptop": credential_row(
            "laptop",
            AGENT,
            owner_actor_id="user-1",
            expires_at="2026-11-08T12:00:00Z",
            last_used_at="2026-11-05T09:00:00Z",
        ),
        "forever": credential_row("forever", AGENT, owner_actor_id="user-1"),
    }
    service = AuthService(
        settings,
        FakeRegistryUnitOfWork(state),
        bootstrap_password_file=FakeBootstrapPasswordFile(),
        clock=lambda: NOW,
    )
    return IdentityWorld(auth=service)


def key_of(credential_id: str | None, scopes: frozenset[str] = SCOPES) -> ActorContext:
    return ActorContext(
        actor_id=AGENT,
        actor_type="agent",
        actor_name="Ada's laptop",
        scopes=scopes,
        credential_id=credential_id,
    )


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def section(answer: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = answer[key]
    assert _is_mapping(value)
    return value


def test_whoami_names_the_key_its_expiry_its_scopes_and_the_tools_they_open(
    settings: Settings,
) -> None:
    answer = whoami(identity_world(settings), key_of("laptop"), {})
    assert answer["actor"] == {"id": AGENT, "name": "Ada's laptop", "type": "agent"}
    assert answer["key"] == {
        "id": "laptop",
        "name": "Token laptop",
        "issued_by": "Ada",
        "created_at": "2026-11-01T09:00:00Z",
        "expires_at": "2026-11-08T12:00:00Z",
        "days_left": 3,
        "expires_soon": True,
        "last_used_at": "2026-11-05T09:00:00Z",
    }
    assert answer["scopes"] == ["boards:read", "cards:read", "loops:read"]
    tools = section(answer, "tools")
    assert list(tools)[:4] == ["whoami", "list_boards", "read_board", "read_loop"]
    assert "list_tickets" in tools
    assert "write_ticket_summaries" not in tools
    assert str(tools["whoami"]).endswith(".")
    assert "Call list_boards" in str(answer["next_step"])


def test_whoami_says_what_each_missing_scope_would_open(settings: Settings) -> None:
    gaps = section(whoami(identity_world(settings), key_of("laptop"), {}), "missing_scopes")
    assert set(gaps) == {
        "cards:write",
        "comments:write",
        "loops:write",
        "loops:generate",
        "history:read",
        "discussions:read",
        "discussions:write",
    }
    # A scope opens the tools that need it and nothing this key lacks besides: cards:write opens
    # write_ticket_summaries, but not create_ticket, which also needs comments:write.
    catalogue = tool_catalog()
    for scope in ("cards:write", "loops:write"):
        alone = [name for name, tool in catalogue.items() if set(tool.scopes) - SCOPES == {scope}]
        assert gaps[scope] == alone
    assert "write_ticket_summaries" in str(gaps["cards:write"])
    assert "create_ticket" not in str(gaps["cards:write"])
    assert "write_note" in str(gaps["loops:write"])
    assert gaps["history:read"] == []


def test_whoami_lists_the_decisions_only_a_person_makes_and_never_token_material(
    settings: Settings,
) -> None:
    answer = whoami(identity_world(settings), key_of("laptop"), {})
    human = section(answer, "human_only")
    assert human["decisions"] == list(HUMAN_DECISIONS)
    assert "human_action_required" in str(human["note"])
    text = json.dumps(answer)
    assert "digest:" not in text
    assert "token_hash" not in text


def test_whoami_without_an_expiry_or_a_key_and_without_its_scope(settings: Settings) -> None:
    world = identity_world(settings)
    forever = section(whoami(world, key_of("forever"), {}), "key")
    assert (forever["expires_at"], forever["days_left"], forever["expires_soon"]) == (
        None,
        None,
        False,
    )
    assert whoami(world, key_of(None), {})["key"] is None  # a session cookie has no key
    assert whoami(world, key_of("gone"), {})["key"] is None
    with pytest.raises(Forbidden):
        whoami(world, key_of("laptop", frozenset({"cards:read"})), {})


def test_whoami_is_offered_first_to_a_key_that_may_list_boards() -> None:
    catalogue = tool_catalog()
    assert next(iter(catalogue)) == "whoami"
    assert catalogue["whoami"].scopes == ("boards:read",)
