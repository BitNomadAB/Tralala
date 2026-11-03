"""Who may do what: role scopes, the token vocabulary and the human-only decisions."""

from __future__ import annotations

from typing import get_args

import pytest

from app.core.context import (
    MEMBER_TOKEN_SCOPES,
    ROLE_ADMIN,
    ROLE_MEMBER,
    SCOPES,
    ActorContext,
    scopes_for_role,
)
from app.core.errors import Forbidden
from app.schemas.auth import Scope
from app.services.auth import _token_scopes

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


def test_an_admin_holds_every_scope() -> None:
    assert scopes_for_role(ROLE_ADMIN) == frozenset(SCOPES)


def test_a_member_works_the_boards_but_does_not_administer_accounts() -> None:
    member = scopes_for_role(ROLE_MEMBER)
    assert member == frozenset(SCOPES) - ADMINISTRATION
    assert "loops:review" in member


@pytest.mark.parametrize("role", [None, "", "owner", "ADMIN"])
def test_an_unknown_role_gets_member_scopes_never_admin(role: str | None) -> None:
    assert scopes_for_role(role) == scopes_for_role(ROLE_MEMBER)


def test_the_grantable_token_scopes_exclude_review_and_administration() -> None:
    """Approving and accepting are human decisions: no token can hold a usable review grant."""
    assert GRANTABLE <= set(SCOPES)
    assert "loops:review" not in GRANTABLE
    assert not GRANTABLE & ADMINISTRATION
    assert {"loops:read", "loops:write", "loops:generate", "history:read"} <= GRANTABLE


def test_the_service_never_issues_an_administration_scope() -> None:
    assert GRANTABLE <= _token_scopes()
    assert not _token_scopes() & ADMINISTRATION


def test_a_personal_token_is_limited_to_working_the_boards() -> None:
    assert set(MEMBER_TOKEN_SCOPES) <= GRANTABLE
    assert len(MEMBER_TOKEN_SCOPES) == len(set(MEMBER_TOKEN_SCOPES))
    assert not [scope for scope in MEMBER_TOKEN_SCOPES if scope.endswith(":admin")]
    assert "boards:write" not in MEMBER_TOKEN_SCOPES


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
