"""Who may do what: role scopes, the token vocabulary, the right to decide in the editor and the
human-only decisions."""

# The pure part of a request or database path is often a private helper; these tests call it
# on purpose (AGENTS.md, Verification contract), so private access is allowed in this file.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import get_args

import pytest

from app.core.config import Settings
from app.core.context import (
    DECIDE_SCOPE,
    KEY_ONLY_SCOPES,
    MEMBER_TOKEN_SCOPES,
    ROLE_ADMIN,
    ROLE_MEMBER,
    SCOPES,
    ActorContext,
    scopes_for_role,
)
from app.core.errors import Forbidden
from app.schemas.auth import Scope
from app.services.agent_tools import tool_catalog
from app.services.auth import _token_scopes
from app.services.auth_tokens import grant_vocabulary

ADMINISTRATION = {"users:admin", "credentials:admin"}
GRANTABLE = set(get_args(Scope))


def _actor(actor_type: str, scopes: set[str], role: str | None = None) -> ActorContext:
    return ActorContext(
        actor_id="actor-1",
        actor_type=actor_type,
        actor_name="Someone",
        scopes=frozenset(scopes),
        role=role,
    )


def test_an_admin_holds_every_scope_but_the_rights_that_live_on_a_key() -> None:
    assert scopes_for_role(ROLE_ADMIN) == frozenset(SCOPES) - KEY_ONLY_SCOPES
    assert {DECIDE_SCOPE} == KEY_ONLY_SCOPES


def test_a_member_works_the_boards_but_does_not_administer_accounts() -> None:
    member = scopes_for_role(ROLE_MEMBER)
    assert member == frozenset(SCOPES) - ADMINISTRATION - KEY_ONLY_SCOPES
    assert "loops:review" in member


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_MEMBER, None])
def test_no_session_holds_the_right_to_decide_in_the_editor(role: str | None) -> None:
    """Only a key its owner gave the right holds it, so holding it says the request came through
    such a key."""
    assert DECIDE_SCOPE not in scopes_for_role(role)


@pytest.mark.parametrize("role", [None, "", "owner", "ADMIN"])
def test_an_unknown_role_gets_member_scopes_never_admin(role: str | None) -> None:
    assert scopes_for_role(role) == scopes_for_role(ROLE_MEMBER)


def test_the_grantable_token_scopes_exclude_review_and_administration() -> None:
    """Approving and accepting are human decisions: no token can hold a usable review grant."""
    assert set(SCOPES) >= GRANTABLE
    assert "loops:review" not in GRANTABLE
    assert not GRANTABLE & ADMINISTRATION
    assert {"loops:read", "loops:write", "loops:generate", "history:read"} <= GRANTABLE


def test_the_service_never_issues_an_administration_scope() -> None:
    assert _token_scopes() >= GRANTABLE
    assert not _token_scopes() & ADMINISTRATION


def test_a_personal_token_is_limited_to_working_the_boards() -> None:
    assert set(MEMBER_TOKEN_SCOPES) <= GRANTABLE
    assert len(MEMBER_TOKEN_SCOPES) == len(set(MEMBER_TOKEN_SCOPES))
    assert not [scope for scope in MEMBER_TOKEN_SCOPES if scope.endswith(":admin")]
    assert "boards:write" not in MEMBER_TOKEN_SCOPES


def test_the_right_to_decide_in_the_editor_is_a_scope_a_person_gives_their_own_key() -> None:
    assert DECIDE_SCOPE == "loops:decide"
    assert DECIDE_SCOPE in SCOPES
    assert DECIDE_SCOPE in GRANTABLE
    assert DECIDE_SCOPE in MEMBER_TOKEN_SCOPES
    assert DECIDE_SCOPE in _token_scopes()


def test_the_right_to_decide_in_the_editor_opens_no_tool() -> None:
    """On its own the right changes nothing a key may call."""
    assert not [tool.name for tool in tool_catalog().values() if DECIDE_SCOPE in tool.scopes]


def test_meta_publishes_the_scopes_as_before_and_whether_editor_decisions_are_on(
    settings: Settings,
) -> None:
    published = grant_vocabulary(settings)
    assert published == {
        "scopes": list(SCOPES),
        "token_scopes": list(get_args(Scope)),
        "member_token_scopes": list(MEMBER_TOKEN_SCOPES),
        "member_token_limits": {
            "live": settings.member_token_limit,
            "default_days": settings.member_token_default_days,
            "max_days": settings.member_token_max_days,
        },
        "editor_decisions": False,
    }
    switched_on = grant_vocabulary(settings.model_copy(update={"editor_decisions": True}))
    assert switched_on == {**published, "editor_decisions": True}


def test_editor_decisions_are_off_unless_the_operator_turns_them_on() -> None:
    assert Settings.model_fields["editor_decisions"].default is False


def test_a_missing_scope_is_named_in_the_refusal() -> None:
    reader = _actor("agent", {"boards:read"})
    assert reader.has_scope("boards:read") is True
    reader.require("boards:read")
    with pytest.raises(Forbidden) as refused:
        reader.require("cards:write")
    assert refused.value.status_code == 403
    assert refused.value.details == {"required_scope": "cards:write"}


@pytest.mark.parametrize("actor_type", ["agent", "service"])
def test_no_scope_lets_a_non_person_take_a_human_decision(actor_type: str) -> None:
    almighty = _actor(actor_type, set(SCOPES), role=ROLE_ADMIN)
    with pytest.raises(Forbidden) as refused:
        almighty.require_human("Approving the analysis")
    assert refused.value.code == "human_action_required"
    assert refused.value.details == {"action": "Approving the analysis", "actor_type": actor_type}
    assert almighty.is_admin is False


def test_a_person_may_take_a_human_decision() -> None:
    person = _actor("user", set(), role=ROLE_MEMBER)
    person.require_human("Approving the analysis")
    assert person.is_admin is False
    assert _actor("user", set(), role=ROLE_ADMIN).is_admin is True
