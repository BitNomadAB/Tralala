"""AuthService's rules on an in-memory registry: sign-in, sessions, accounts, invitations, tokens.

The service runs its real code; only the repositories, the unit of work, the clock, the id source
and the password hashing are replaced (tokens, session values and CSRF values stay real). The
password hash is a readable stand-in so a test can say which password a person has without paying
for scrypt; one test proves the defaults are the real primitives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core import security
from app.core.config import Settings
from app.core.context import MEMBER_TOKEN_SCOPES, ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailure
from app.core.security import (
    BOOTSTRAP_PASSWORD_FILE_NAME,
    create_session_value,
    hash_token,
    read_session_value,
)
from app.repositories.registry import RegistryUnitOfWork
from app.schemas.auth import CredentialCreate, PreferencesUpdate
from app.services.auth import AuthService, stored_scopes
from tests.unit.fakes.registry import (
    CREATED,
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    credential_row,
    invite_row,
    registry_unit_of_work,
    session_row,
    sign_in_row,
)

# A clock with a fraction of a second: stored times are whole seconds, truncated.
NOW = datetime(2026, 11, 3, 10, 0, 0, 700_000, tzinfo=UTC)
NOW_TEXT = "2026-11-03T10:00:00Z"
EARLIER = "2026-11-02T08:00:00Z"
LATER = "2026-12-01T00:00:00Z"

ADMIN_ID = "admin-1"
MEMBER_ID = "member-1"
ADMIN_PASSWORD = "ada-lovelace-1815"
MEMBER_PASSWORD = "bob-the-builder-9"
ADMIN = ActorContext(
    actor_id=ADMIN_ID,
    actor_type="user",
    actor_name="Ada",
    scopes=scopes_for_role("admin"),
    role="admin",
)
MEMBER = ActorContext(
    actor_id=MEMBER_ID,
    actor_type="user",
    actor_name="Bob",
    scopes=scopes_for_role("member"),
    role="member",
)
AGENT = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Robot", scopes=frozenset({"boards:read"})
)


def unit_of_work_is_what_auth_service_needs(state: RegistryState) -> RegistryUnitOfWork:
    """Never called: pyright proves the fake unit of work fits the Protocol AuthService takes."""
    return registry_unit_of_work(state)


def hashed(password: str) -> str:
    return f"hashed:{password}"


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Verifier:
    """The stand-in for ``verify_password``, remembering what it was asked to compare."""

    calls: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def __call__(self, password: str, stored: str) -> bool:
        self.calls.append((password, stored))
        return stored == hashed(password)


@dataclass(slots=True)
class Registry:
    state: RegistryState
    store: FakeRegistryUnitOfWork
    service: AuthService
    verifier: Verifier

    def session_value(self, session_id: str) -> str:
        value, _ = create_session_value(self.service.secret_key, session_id, 3600)
        return value

    def live_sessions(self, actor_id: str) -> list[str]:
        return [
            row.id
            for row in self.state.sessions.values()
            if row.actor_id == actor_id and row.revoked_at is None
        ]


def make_registry(settings: Settings, *, clock: datetime = NOW) -> Registry:
    """Ada (administrator) and Bob (member), each with a password and no session or token."""
    state = RegistryState()
    for actor_id, name, role, password in (
        (ADMIN_ID, "Ada", "admin", ADMIN_PASSWORD),
        (MEMBER_ID, "Bob", "member", MEMBER_PASSWORD),
    ):
        state.actors[actor_id] = actor_row(actor_id, name=name)
        state.sign_ins[actor_id] = sign_in_row(actor_id, password_hash=hashed(password), role=role)
    store = FakeRegistryUnitOfWork(state)
    verifier = Verifier()
    service = AuthService(
        settings,
        store,
        clock=lambda: clock,
        new_id=Ids(),
        password_hasher=hashed,
        password_verifier=verifier,
    )
    return Registry(state, store, service, verifier)


@pytest.fixture
def registry(settings: Settings) -> Registry:
    return make_registry(settings)


def add_token(
    registry: Registry,
    credential_id: str,
    *,
    owner: str | None = MEMBER_ID,
    revoked_at: str | None = None,
    expires_at: str | None = None,
    scopes: str = '["boards:read", "cards:read"]',
    disabled: bool = False,
) -> str:
    """A token row and its agent actor; returns the raw token."""
    token = f"trl_{credential_id}"
    agent_id = f"agent-{credential_id}"
    registry.state.actors[agent_id] = actor_row(
        agent_id,
        type_="agent",
        name=f"Agent {credential_id}",
        disabled_at=EARLIER if disabled else None,
    )
    registry.state.credentials[credential_id] = credential_row(
        credential_id,
        agent_id,
        token_hash=hash_token(token),
        scopes=scopes,
        owner_actor_id=owner,
        revoked_at=revoked_at,
        expires_at=expires_at,
    )
    return token


# --- the defaults ------------------------------------------------------------------------------


def test_the_service_hashes_with_the_real_primitives_unless_told_otherwise(
    settings: Settings, tmp_path: Path
) -> None:
    configured = settings.model_copy(update={"data_dir": tmp_path})
    state = RegistryState()
    service = AuthService(configured, FakeRegistryUnitOfWork(state))
    service.bootstrap_admin()  # the shipped placeholder: a generated password, hashed for real

    (sign_in,) = state.sign_ins.values()
    password = (tmp_path / BOOTSTRAP_PASSWORD_FILE_NAME).read_text(encoding="utf-8").strip()
    assert sign_in.password_hash.startswith("scrypt$")
    assert security.verify_password(password, sign_in.password_hash)
    assert service.login(configured.bootstrap_username, password)["actor"]["role"] == "admin"


# --- first start ---------------------------------------------------------------------------------


def test_bootstrap_does_nothing_once_a_person_exists(registry: Registry) -> None:
    before = dict(registry.state.actors)

    registry.service.bootstrap_admin()

    assert registry.state.actors == before
    assert registry.store.commits == 0


def test_bootstrap_creates_the_configured_administrator_without_a_password_file(
    settings: Settings, tmp_path: Path
) -> None:
    configured = settings.model_copy(
        update={
            "data_dir": tmp_path,
            "bootstrap_username": "root",
            "bootstrap_password": "a-chosen-strong-password",
        }
    )
    registry = make_registry(configured)
    registry.state.actors.clear()
    registry.state.sign_ins.clear()

    registry.service.bootstrap_admin()

    (actor,) = registry.state.actors.values()
    assert (actor.name, actor.type, actor.created_at, actor.disabled_at) == (
        "root",
        "user",
        NOW_TEXT,
        None,
    )
    assert registry.state.sign_ins[actor.id] == sign_in_row(
        actor.id, password_hash=hashed("a-chosen-strong-password"), role="admin"
    ).__replace__(updated_at=NOW_TEXT)
    assert not (tmp_path / BOOTSTRAP_PASSWORD_FILE_NAME).exists()
    assert registry.store.commits == 1


@pytest.mark.parametrize("placeholder", ["admin", "  Password ", "tralala-dev-1", ""])
def test_bootstrap_replaces_a_placeholder_password_and_writes_it_once(
    settings: Settings, tmp_path: Path, placeholder: str
) -> None:
    configured = settings.model_copy(
        update={"data_dir": tmp_path, "bootstrap_password": placeholder}
    )
    registry = make_registry(configured)
    registry.state.actors.clear()
    registry.state.sign_ins.clear()

    registry.service.bootstrap_admin()

    written = (tmp_path / BOOTSTRAP_PASSWORD_FILE_NAME).read_text(encoding="utf-8")
    password = written.removesuffix("\n")
    assert written.endswith("\n")
    assert len(password) >= 20
    assert password.strip().lower() != placeholder.strip().lower()
    (sign_in,) = registry.state.sign_ins.values()
    assert sign_in.password_hash == hashed(password)


def test_startup_purges_expired_and_revoked_sessions_and_keeps_live_ones(
    registry: Registry,
) -> None:
    for session_id, expires_at, revoked_at in (
        ("expired", EARLIER, None),
        ("revoked", LATER, EARLIER),
        ("live", LATER, None),
        ("ends-now", NOW_TEXT, None),
    ):
        registry.state.sessions[session_id] = session_row(
            session_id,
            ADMIN_ID,
            token_hash=f"digest-{session_id}",
            expires_at=expires_at,
            revoked_at=revoked_at,
        )

    assert registry.service.purge_expired_sessions() == 2

    assert set(registry.state.sessions) == {"live", "ends-now"}


# --- signing in ----------------------------------------------------------------------------------


def test_login_opens_a_session_and_returns_the_person_with_their_scopes(
    registry: Registry,
) -> None:
    registry.state.sign_ins[MEMBER_ID] = registry.state.sign_ins[MEMBER_ID].__replace__(
        theme_mode="dark", theme_kit="classic"
    )

    result = registry.service.login("Bob", MEMBER_PASSWORD)

    assert result["actor"] == {
        "id": MEMBER_ID,
        "type": "user",
        "name": "Bob",
        "role": "member",
        "scopes": sorted(scopes_for_role("member")),
        "preferences": {"theme_mode": "dark", "theme_kit": "classic"},
    }
    ttl = registry.service.settings.session_ttl_seconds
    assert result["expires_at"] == (NOW + timedelta(seconds=ttl)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert result["csrf_token"]
    parsed = read_session_value(registry.service.secret_key, result["session"])
    assert parsed is not None
    (session,) = registry.state.sessions.values()
    assert session == session_row(
        "new-1",
        MEMBER_ID,
        token_hash=hash_token(parsed[0]),
        expires_at=result["expires_at"],
        last_seen_at=NOW_TEXT,
    ).__replace__(created_at=NOW_TEXT)


def test_a_wrong_password_opens_no_session(registry: Registry) -> None:
    with pytest.raises(Unauthorized) as refused:
        registry.service.login("Bob", ADMIN_PASSWORD)

    assert refused.value.code == "invalid_credentials"
    assert registry.state.sessions == {}


def test_an_unknown_name_is_refused_after_the_same_hashing_work(registry: Registry) -> None:
    with pytest.raises(Unauthorized) as refused:
        registry.service.login("Nobody", MEMBER_PASSWORD)

    assert refused.value.code == "invalid_credentials"
    ((password, stored),) = registry.verifier.calls
    assert password == MEMBER_PASSWORD
    assert stored.startswith("scrypt$")  # the dummy hash: the work does not reveal the name


def test_a_disabled_person_cannot_sign_in(registry: Registry) -> None:
    registry.state.actors[MEMBER_ID] = registry.state.actors[MEMBER_ID].__replace__(
        disabled_at=EARLIER
    )

    with pytest.raises(Unauthorized) as refused:
        registry.service.login("Bob", MEMBER_PASSWORD)

    assert refused.value.code == "invalid_credentials"


def test_logout_revokes_the_session_once(registry: Registry) -> None:
    value = registry.service.login("Bob", MEMBER_PASSWORD)["session"]

    assert registry.service.logout(value) is True
    assert registry.service.logout(value) is False
    (session,) = registry.state.sessions.values()
    assert session.revoked_at == NOW_TEXT


@pytest.mark.parametrize("value", [None, "", "not-a-session-value", "a.b.c"])
def test_logout_without_a_valid_session_value_changes_nothing(
    registry: Registry, value: str | None
) -> None:
    assert registry.service.logout(value) is False
    assert registry.store.commits == 0


# --- sessions ------------------------------------------------------------------------------------


def _session(
    registry: Registry,
    *,
    token_hash: str = "",
    expires_at: str = LATER,
    last_seen_at: str = CREATED,
    revoked_at: str | None = None,
) -> str:
    """Bob's session ``s-1``; returns its signed cookie value."""
    registry.state.sessions["s-1"] = session_row(
        "s-1",
        MEMBER_ID,
        token_hash=token_hash or hash_token("raw-s-1"),
        expires_at=expires_at,
        last_seen_at=last_seen_at,
        revoked_at=revoked_at,
    )
    return registry.session_value("raw-s-1")


def test_a_live_session_is_the_person_with_their_role_and_scopes(registry: Registry) -> None:
    actor = registry.service.actor_from_session(_session(registry))

    assert actor == ActorContext(
        actor_id=MEMBER_ID,
        actor_type="user",
        actor_name="Bob",
        scopes=scopes_for_role("member"),
        role="member",
    )
    assert registry.state.sessions["s-1"].last_seen_at == NOW_TEXT


def test_a_session_seen_recently_is_not_written_again(registry: Registry) -> None:
    recently = (NOW - timedelta(seconds=299)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a_while_ago = (NOW - timedelta(seconds=301)).strftime("%Y-%m-%dT%H:%M:%SZ")

    registry.service.actor_from_session(_session(registry, last_seen_at=recently))
    assert registry.state.sessions["s-1"].last_seen_at == recently

    registry.service.actor_from_session(_session(registry, last_seen_at=a_while_ago))
    assert registry.state.sessions["s-1"].last_seen_at == NOW_TEXT


@pytest.mark.parametrize(
    ("revoked_at", "expires_at", "token_hash"),
    [(EARLIER, LATER, ""), (None, EARLIER, ""), (None, LATER, "another-digest")],
)
def test_a_revoked_expired_or_unknown_session_is_refused(
    registry: Registry, revoked_at: str | None, expires_at: str, token_hash: str
) -> None:
    value = _session(
        registry, revoked_at=revoked_at, expires_at=expires_at, token_hash=token_hash
    )

    with pytest.raises(Unauthorized) as refused:
        registry.service.actor_from_session(value)

    assert refused.value.code == "invalid_session"
    assert registry.store.commits == 0


def test_the_session_of_a_disabled_person_is_refused(registry: Registry) -> None:
    value = _session(registry)
    registry.state.actors[MEMBER_ID] = registry.state.actors[MEMBER_ID].__replace__(
        disabled_at=EARLIER
    )

    with pytest.raises(Unauthorized) as refused:
        registry.service.actor_from_session(value)

    assert refused.value.code == "invalid_session"


def test_a_session_value_signed_by_another_installation_is_refused(registry: Registry) -> None:
    _session(registry)
    forged, _ = create_session_value("another-installation-secret-" + "x" * 24, "raw-s-1", 3600)

    with pytest.raises(Unauthorized) as refused:
        registry.service.actor_from_session(forged)

    assert refused.value.code == "invalid_session"


# --- API tokens as identity ----------------------------------------------------------------------


def test_a_live_token_is_its_agent_with_the_stored_scopes_and_records_its_use(
    registry: Registry,
) -> None:
    token = add_token(registry, "t-1", expires_at=LATER)

    actor = registry.service.actor_from_token(token)

    assert actor == ActorContext(
        actor_id="agent-t-1",
        actor_type="agent",
        actor_name="Agent t-1",
        scopes=frozenset({"boards:read", "cards:read"}),
    )
    assert registry.state.credentials["t-1"].last_used_at == NOW_TEXT


def test_a_token_without_expiry_stays_valid(registry: Registry) -> None:
    token = add_token(registry, "t-1", expires_at=None)

    assert registry.service.actor_from_token(token).actor_id == "agent-t-1"


@pytest.mark.parametrize(
    ("revoked_at", "expires_at", "disabled", "code"),
    [
        (EARLIER, LATER, False, "token_revoked"),
        (None, LATER, True, "token_revoked"),
        (None, EARLIER, False, "token_expired"),
    ],
)
def test_a_revoked_disabled_or_expired_token_is_refused(
    registry: Registry, revoked_at: str | None, expires_at: str, disabled: bool, code: str
) -> None:
    token = add_token(
        registry, "t-1", revoked_at=revoked_at, expires_at=expires_at, disabled=disabled
    )

    with pytest.raises(Unauthorized) as refused:
        registry.service.actor_from_token(token)

    assert refused.value.code == code
    assert registry.state.credentials["t-1"].last_used_at is None


def test_an_unknown_token_is_refused(registry: Registry) -> None:
    add_token(registry, "t-1")

    with pytest.raises(Unauthorized) as refused:
        registry.service.actor_from_token("trl_guessed")

    assert refused.value.code == "invalid_token"


@pytest.mark.parametrize(
    ("raw", "scopes"),
    [
        ('["boards:read", "cards:write"]', ["boards:read", "cards:write"]),
        ("[]", []),
        ('["boards:read", 7, null]', ["boards:read"]),
        ('{"users:admin": true}', []),
        ('"boards:read"', []),
        ("not json", []),
    ],
)
def test_a_token_holds_only_the_names_in_its_stored_list(raw: str, scopes: list[str]) -> None:
    assert stored_scopes(raw) == scopes


# --- preferences ---------------------------------------------------------------------------------


def test_an_agent_has_no_preferences_and_cannot_set_any(registry: Registry) -> None:
    assert registry.service.preferences(AGENT) == {"theme_mode": None, "theme_kit": None}
    with pytest.raises(Forbidden):
        registry.service.update_preferences(AGENT, PreferencesUpdate(theme_mode="dark"))


def test_preferences_change_only_the_fields_sent_and_null_clears_one(registry: Registry) -> None:
    registry.state.sign_ins[MEMBER_ID] = registry.state.sign_ins[MEMBER_ID].__replace__(
        theme_mode="light", theme_kit="classic"
    )

    changed = registry.service.update_preferences(MEMBER, PreferencesUpdate(theme_mode="dark"))
    assert changed == {"theme_mode": "dark", "theme_kit": "classic"}

    cleared = registry.service.update_preferences(
        MEMBER, PreferencesUpdate.model_validate({"theme_kit": None})
    )
    assert cleared == {"theme_mode": "dark", "theme_kit": None}
    assert registry.service.preferences(MEMBER) == cleared
    assert registry.state.sign_ins[MEMBER_ID].updated_at == NOW_TEXT


# --- passwords -----------------------------------------------------------------------------------


def test_changing_a_password_revokes_every_session_of_the_person(registry: Registry) -> None:
    registry.service.login("Bob", MEMBER_PASSWORD)
    registry.service.login("Bob", MEMBER_PASSWORD)
    registry.service.login("Ada", ADMIN_PASSWORD)

    result = registry.service.change_password(MEMBER, MEMBER_PASSWORD, "a-brand-new-secret")

    assert result == {"changed": True, "revoked_sessions": 2}
    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed("a-brand-new-secret")
    assert registry.live_sessions(MEMBER_ID) == []
    assert len(registry.live_sessions(ADMIN_ID)) == 1


def test_a_password_change_needs_the_current_password_and_a_person(registry: Registry) -> None:
    # Neither is a 401: the caller is authenticated, and a client ends its session on a 401 (a
    # mistyped current password used to sign the browser tab out).
    registry.service.login("Bob", MEMBER_PASSWORD)
    with pytest.raises(ValidationFailure) as wrong:
        registry.service.change_password(MEMBER, "not-my-password", "a-brand-new-secret")
    assert (wrong.value.status_code, wrong.value.code) == (422, "invalid_credentials")
    assert wrong.value.message == "Current password is incorrect"
    assert len(registry.live_sessions(MEMBER_ID)) == 1

    with pytest.raises(Forbidden) as token:
        registry.service.change_password(AGENT, "x", "a-brand-new-secret")
    assert (token.value.status_code, token.value.code) == (403, "forbidden")

    ghost = ActorContext(actor_id="gone", actor_type="user", actor_name="Gone")
    with pytest.raises(Unauthorized) as missing:
        registry.service.change_password(ghost, "x", "a-brand-new-secret")
    assert missing.value.message == "Account not found"
    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed(MEMBER_PASSWORD)


@pytest.mark.parametrize("weak", ["short", "password", "Bob"])
def test_a_new_password_follows_the_policy(registry: Registry, weak: str) -> None:
    with pytest.raises(ValidationFailure):
        registry.service.change_password(MEMBER, MEMBER_PASSWORD, weak)
    with pytest.raises(ValidationFailure):
        registry.service.reset_password(ADMIN, MEMBER_ID, weak)

    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed(MEMBER_PASSWORD)


def test_an_administrator_resets_a_password_and_the_sessions_go(registry: Registry) -> None:
    registry.service.login("Bob", MEMBER_PASSWORD)

    result = registry.service.reset_password(ADMIN, MEMBER_ID, "set-by-the-admin-1")

    assert result == {"id": MEMBER_ID, "revoked_sessions": 1}
    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed("set-by-the-admin-1")
    with pytest.raises(NotFound):
        registry.service.reset_password(ADMIN, "nobody", "set-by-the-admin-1")
    with pytest.raises(Forbidden):
        registry.service.reset_password(MEMBER, ADMIN_ID, "set-by-the-admin-1")


# --- accounts ------------------------------------------------------------------------------------


def test_the_user_list_shows_each_persons_live_agent_access(registry: Registry) -> None:
    registry.state.actors["carol"] = actor_row(
        "carol", name="Carol", created_at="2026-10-01T00:00:00Z", disabled_at=EARLIER
    )
    registry.state.sign_ins["carol"] = sign_in_row("carol")
    add_token(registry, "t-1")
    add_token(registry, "t-2", revoked_at=EARLIER)
    registry.state.credentials["t-1"] = registry.state.credentials["t-1"].__replace__(
        last_used_at=EARLIER
    )
    add_token(registry, "t-3")

    entries = registry.service.list_users(ADMIN)

    assert [entry["name"] for entry in entries] == ["Carol", "Ada", "Bob"]
    carol, ada, bob = entries
    assert list(bob) == [
        "id",
        "name",
        "created_at",
        "disabled_at",
        "role",
        "updated_at",
        "disabled",
        "agent_access_count",
        "agent_access_last_used_at",
    ]
    assert (bob["agent_access_count"], bob["agent_access_last_used_at"]) == (2, EARLIER)
    assert (ada["agent_access_count"], ada["agent_access_last_used_at"]) == (0, None)
    assert (carol["disabled"], carol["disabled_at"], ada["disabled"]) == (True, EARLIER, False)
    with pytest.raises(Forbidden):
        registry.service.list_users(MEMBER)


def test_an_administrator_creates_a_person(registry: Registry) -> None:
    created = registry.service.create_user(
        ADMIN, name="Carol", password="carols-own-secret", role="member"
    )

    assert created == {
        "id": "new-1",
        "name": "Carol",
        "role": "member",
        "created_at": NOW_TEXT,
        "disabled": False,
    }
    assert registry.state.actors["new-1"] == actor_row("new-1", name="Carol", created_at=NOW_TEXT)
    assert registry.state.sign_ins["new-1"] == sign_in_row(
        "new-1", password_hash=hashed("carols-own-secret")
    ).__replace__(updated_at=NOW_TEXT)


def test_creating_a_person_checks_scope_role_password_and_name_in_that_order(
    registry: Registry,
) -> None:
    with pytest.raises(Forbidden):
        registry.service.create_user(MEMBER, name="Bob", password="x", role="owner")
    with pytest.raises(ValidationFailure) as role:
        registry.service.create_user(ADMIN, name="Bob", password="x", role="owner")
    assert role.value.details == {"allowed": ["admin", "member"]}
    with pytest.raises(ValidationFailure):
        registry.service.create_user(ADMIN, name="Bob", password="x", role="member")
    with pytest.raises(Conflict) as taken:
        registry.service.create_user(ADMIN, name="Bob", password="long-enough-1", role="member")
    assert taken.value.details == {"name": "Bob"}
    assert len(registry.state.actors) == 2


def test_the_name_of_a_disabled_person_can_be_given_again(registry: Registry) -> None:
    registry.state.actors[MEMBER_ID] = registry.state.actors[MEMBER_ID].__replace__(
        disabled_at=EARLIER
    )

    created = registry.service.create_user(
        ADMIN, name="Bob", password="long-enough-1", role="member"
    )

    assert created["name"] == "Bob"
    assert len(registry.state.actors) == 3


def test_a_role_change_revokes_the_sessions_and_answers_the_account(registry: Registry) -> None:
    registry.service.login("Bob", MEMBER_PASSWORD)
    add_token(registry, "t-1")

    updated = registry.service.update_user(ADMIN, MEMBER_ID, role="admin", disabled=None)

    assert updated == {
        "id": MEMBER_ID,
        "name": "Bob",
        "role": "admin",
        "created_at": CREATED,
        "disabled": False,
        "agent_access_count": 1,
        "agent_access_last_used_at": None,
    }
    assert registry.live_sessions(MEMBER_ID) == []
    assert registry.state.credentials["t-1"].revoked_at is None


def test_disabling_a_person_revokes_their_sessions_and_everything_they_issued_at_once(
    registry: Registry,
) -> None:
    registry.service.login("Bob", MEMBER_PASSWORD)
    add_token(registry, "t-1")
    add_token(registry, "t-2")
    add_token(registry, "admins", owner=ADMIN_ID)
    commits = registry.store.commits

    updated = registry.service.update_user(ADMIN, MEMBER_ID, role=None, disabled=True)

    assert (updated["disabled"], updated["agent_access_count"]) == (True, 0)
    assert registry.state.actors[MEMBER_ID].disabled_at == NOW_TEXT
    assert registry.live_sessions(MEMBER_ID) == []
    for credential_id in ("t-1", "t-2"):
        assert registry.state.credentials[credential_id].revoked_at == NOW_TEXT
        assert registry.state.actors[f"agent-{credential_id}"].disabled_at == NOW_TEXT
    assert registry.state.credentials["admins"].revoked_at is None
    assert registry.state.actors["agent-admins"].disabled_at is None
    assert registry.store.commits == commits + 1


def test_enabling_a_person_again_restores_the_account_but_not_what_was_revoked(
    registry: Registry,
) -> None:
    add_token(registry, "t-1")
    registry.service.update_user(ADMIN, MEMBER_ID, role=None, disabled=True)

    updated = registry.service.update_user(ADMIN, MEMBER_ID, role=None, disabled=False)

    assert updated["disabled"] is False
    assert registry.state.actors[MEMBER_ID].disabled_at is None
    assert registry.state.credentials["t-1"].revoked_at == NOW_TEXT


@pytest.mark.parametrize(
    ("role", "disabled"), [("member", None), (None, True), ("member", True)]
)
def test_the_last_enabled_administrator_stays(
    registry: Registry, role: str | None, disabled: bool | None
) -> None:
    with pytest.raises(Conflict):
        registry.service.update_user(ADMIN, ADMIN_ID, role=role, disabled=disabled)

    assert registry.state.sign_ins[ADMIN_ID].role == "admin"
    assert registry.state.actors[ADMIN_ID].disabled_at is None
    assert registry.store.rollbacks == 1


def test_an_administrator_may_step_down_when_another_one_remains(registry: Registry) -> None:
    registry.service.update_user(ADMIN, MEMBER_ID, role="admin", disabled=None)

    updated = registry.service.update_user(ADMIN, ADMIN_ID, role="member", disabled=None)

    assert updated["role"] == "member"


def test_updating_an_unknown_person_or_with_an_unknown_role_is_refused(
    registry: Registry,
) -> None:
    with pytest.raises(NotFound):
        registry.service.update_user(ADMIN, "nobody", role="owner", disabled=None)
    with pytest.raises(ValidationFailure):
        registry.service.update_user(ADMIN, MEMBER_ID, role="owner", disabled=None)
    with pytest.raises(Forbidden):
        registry.service.update_user(MEMBER, MEMBER_ID, role="admin", disabled=None)


# --- invitations ---------------------------------------------------------------------------------


def test_an_invitation_is_returned_once_and_stored_hashed(registry: Registry) -> None:
    issued = registry.service.create_invite(ADMIN, MEMBER_ID, expires_in_hours=2)

    assert issued == {
        "user_id": MEMBER_ID,
        "user_name": "Bob",
        "token": issued["token"],
        "path": f"/enrol?token={issued['token']}",
        "expires_at": "2026-11-03T12:00:00Z",
    }
    assert issued["token"].startswith("trl_")
    assert registry.state.invites["new-1"] == invite_row(
        "new-1",
        MEMBER_ID,
        token_hash=hash_token(issued["token"]),
        expires_at="2026-11-03T12:00:00Z",
        created_by_actor_id=ADMIN_ID,
    ).__replace__(created_at=NOW_TEXT)


def test_an_invitation_lasts_the_configured_hours_by_default(registry: Registry) -> None:
    hours = registry.service.settings.invite_ttl_hours

    issued = registry.service.create_invite(ADMIN, MEMBER_ID)

    expected = (NOW + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert issued["expires_at"] == expected


def test_a_new_invitation_replaces_an_unused_one_and_keeps_used_ones(registry: Registry) -> None:
    registry.state.invites["old"] = invite_row(
        "old", MEMBER_ID, token_hash="digest-old", expires_at=LATER
    )
    registry.state.invites["used"] = invite_row(
        "used", MEMBER_ID, token_hash="digest-used", expires_at=LATER, used_at=EARLIER
    )
    registry.state.invites["other"] = invite_row(
        "other", ADMIN_ID, token_hash="digest-other", expires_at=LATER
    )

    registry.service.create_invite(ADMIN, MEMBER_ID)

    assert set(registry.state.invites) == {"used", "other", "new-1"}


def test_only_an_enabled_known_person_is_invited(registry: Registry) -> None:
    with pytest.raises(NotFound):
        registry.service.create_invite(ADMIN, "nobody")
    registry.state.actors[MEMBER_ID] = registry.state.actors[MEMBER_ID].__replace__(
        disabled_at=EARLIER
    )
    with pytest.raises(Conflict) as disabled:
        registry.service.create_invite(ADMIN, MEMBER_ID)
    assert disabled.value.code == "user_disabled"
    with pytest.raises(Forbidden):
        registry.service.create_invite(MEMBER, ADMIN_ID)
    assert registry.state.invites == {}


def test_accepting_an_invitation_sets_the_password_and_signs_the_person_in(
    registry: Registry,
) -> None:
    registry.service.login("Bob", MEMBER_PASSWORD)
    token = registry.service.create_invite(ADMIN, MEMBER_ID)["token"]

    signed_in = registry.service.accept_invite(token, "chosen-on-enrolment")

    assert signed_in["actor"]["id"] == MEMBER_ID
    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed("chosen-on-enrolment")
    assert registry.state.invites["new-2"].used_at == NOW_TEXT
    # The session opened before the invitation was revoked; the new one is live.
    assert registry.live_sessions(MEMBER_ID) == [signed_in_session_id(registry)]
    with pytest.raises(Unauthorized) as again:
        registry.service.accept_invite(token, "chosen-on-enrolment")
    assert again.value.code == "invite_used"


def signed_in_session_id(registry: Registry) -> str:
    return max(registry.state.sessions)


@pytest.mark.parametrize(
    ("expires_at", "used_at", "disabled_at", "code"),
    [
        (EARLIER, None, None, "invite_expired"),
        (LATER, EARLIER, None, "invite_used"),
        (LATER, None, EARLIER, "user_disabled"),
    ],
)
def test_an_expired_used_or_disabled_invitation_is_refused(
    registry: Registry,
    expires_at: str,
    used_at: str | None,
    disabled_at: str | None,
    code: str,
) -> None:
    registry.state.invites["i-1"] = invite_row(
        "i-1",
        MEMBER_ID,
        token_hash=hash_token("trl_invite"),
        expires_at=expires_at,
        used_at=used_at,
    )
    registry.state.actors[MEMBER_ID] = registry.state.actors[MEMBER_ID].__replace__(
        disabled_at=disabled_at
    )

    with pytest.raises(Unauthorized) as refused:
        registry.service.accept_invite("trl_invite", "chosen-on-enrolment")

    assert refused.value.code == code
    assert registry.state.sign_ins[MEMBER_ID].password_hash == hashed(MEMBER_PASSWORD)


def test_an_unknown_invitation_and_a_weak_password_are_refused(registry: Registry) -> None:
    with pytest.raises(Unauthorized) as unknown:
        registry.service.accept_invite("trl_unknown", "chosen-on-enrolment")
    assert unknown.value.code == "invite_invalid"

    token = registry.service.create_invite(ADMIN, MEMBER_ID)["token"]
    with pytest.raises(ValidationFailure):
        registry.service.accept_invite(token, "Bob")
    assert registry.state.invites["new-1"].used_at is None


# --- issuing API tokens --------------------------------------------------------------------------


def _create(scopes: list[str], days: int | None = None, name: str = "Helper") -> CredentialCreate:
    return CredentialCreate.model_validate(
        {"name": name, "scopes": scopes, "expires_in_days": days}
    )


def test_an_administrator_issues_a_token_that_is_stored_hashed_and_returned_once(
    registry: Registry,
) -> None:
    issued = registry.service.create_credential(ADMIN, _create(["boards:write"], days=10))

    assert issued == {
        "id": "new-2",
        "actor_id": "new-1",
        "owner_actor_id": ADMIN_ID,
        "name": "Helper",
        "scopes": ["boards:write"],
        "created_at": NOW_TEXT,
        "expires_at": "2026-11-13T10:00:00Z",
        "revoked_at": None,
        "last_used_at": None,
        "actor_name": "Helper",
        "owner_name": "Ada",
        "token": issued["token"],
    }
    assert registry.state.actors["new-1"] == actor_row(
        "new-1", type_="agent", name="Helper", created_at=NOW_TEXT
    )
    stored = registry.state.credentials["new-2"]
    assert stored.token_hash == hash_token(issued["token"])
    assert json.loads(stored.scopes) == ["boards:write"]
    assert registry.service.actor_from_token(issued["token"]).actor_id == "new-1"


def test_an_administrators_token_expires_by_default_or_never_when_asked(
    registry: Registry,
) -> None:
    days = registry.service.settings.credential_default_ttl_days

    default = registry.service.create_credential(ADMIN, _create(["boards:read"]))
    never = registry.service.create_credential(ADMIN, _create(["boards:read"], days=0))

    expected = (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert (default["expires_at"], never["expires_at"]) == (expected, None)


def test_a_token_never_holds_an_administration_scope(registry: Registry) -> None:
    payload = CredentialCreate.model_construct(
        name="Sneaky", scopes=["boards:read", "users:admin"], expires_in_days=None
    )

    with pytest.raises(ValidationFailure) as refused:
        registry.service.create_credential(ADMIN, payload)

    assert refused.value.details == {"unknown_scopes": ["users:admin"]}
    assert registry.state.credentials == {}


def test_a_member_issues_their_own_time_boxed_access(registry: Registry) -> None:
    settings = registry.service.settings

    default = registry.service.create_credential(MEMBER, _create(["cards:write"]))
    capped = registry.service.create_credential(MEMBER, _create(["cards:write"], days=3650))

    assert default["owner_actor_id"] == MEMBER_ID
    default_end = NOW + timedelta(days=settings.member_token_default_days)
    capped_end = NOW + timedelta(days=settings.member_token_max_days)
    assert default["expires_at"] == default_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert capped["expires_at"] == capped_end.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_members_access_stays_within_the_member_vocabulary(registry: Registry) -> None:
    with pytest.raises(ValidationFailure) as refused:
        registry.service.create_credential(MEMBER, _create(["cards:read", "boards:write"]))

    assert refused.value.code == "forbidden_scope"
    assert refused.value.details == {
        "outside": ["boards:write"],
        "allowed": list(MEMBER_TOKEN_SCOPES),
    }


def test_a_members_access_needs_an_expiry(registry: Registry) -> None:
    with pytest.raises(ValidationFailure) as refused:
        registry.service.create_credential(MEMBER, _create(["cards:read"], days=0))

    assert refused.value.code == "expiry_required"


def test_a_member_holds_at_most_the_configured_number_of_live_accesses(
    registry: Registry,
) -> None:
    limit = registry.service.settings.member_token_limit
    for index in range(limit):
        add_token(registry, f"t-{index}")
    add_token(registry, "revoked", revoked_at=EARLIER)
    add_token(registry, "admins", owner=ADMIN_ID)

    with pytest.raises(Conflict) as refused:
        registry.service.create_credential(MEMBER, _create(["cards:read"]))

    assert refused.value.code == "agent_access_limit"
    assert refused.value.details == {"limit": limit, "live": limit}


# --- listing, rotating and revoking tokens -------------------------------------------------------


def test_a_member_lists_only_their_own_tokens_whatever_they_ask(registry: Registry) -> None:
    add_token(registry, "mine")
    add_token(registry, "admins", owner=ADMIN_ID)

    listed = registry.service.list_credentials(MEMBER, owner_id=ADMIN_ID)

    assert [entry["id"] for entry in listed] == ["mine"]
    assert listed[0] == {
        "id": "mine",
        "actor_id": "agent-mine",
        "owner_actor_id": MEMBER_ID,
        "actor_name": "Agent mine",
        "owner_name": "Bob",
        "name": "Token mine",
        "scopes": ["boards:read", "cards:read"],
        "created_at": CREATED,
        "expires_at": None,
        "last_used_at": None,
        "revoked_at": None,
    }


def test_an_administrator_lists_every_token_newest_first_or_one_persons(
    registry: Registry,
) -> None:
    add_token(registry, "older")
    add_token(registry, "admins", owner=ADMIN_ID)
    add_token(registry, "unowned", owner=None)
    registry.state.credentials["admins"] = registry.state.credentials["admins"].__replace__(
        created_at=NOW_TEXT
    )

    everything = registry.service.list_credentials(ADMIN)
    blank = registry.service.list_credentials(ADMIN, owner_id="")
    bobs = registry.service.list_credentials(ADMIN, owner_id=MEMBER_ID)

    assert everything[0]["id"] == "admins"
    assert {entry["id"] for entry in everything} == {"older", "admins", "unowned"}
    assert blank == everything
    assert [entry["id"] for entry in bobs] == ["older"]
    assert next(e for e in everything if e["id"] == "unowned")["owner_name"] is None


def test_revoking_a_token_disables_its_agent_and_a_second_revoke_finds_nothing(
    registry: Registry,
) -> None:
    add_token(registry, "t-1")

    assert registry.service.revoke_credential(MEMBER, "t-1") is True

    assert registry.state.credentials["t-1"].revoked_at == NOW_TEXT
    assert registry.state.actors["agent-t-1"].disabled_at == NOW_TEXT
    with pytest.raises(NotFound):
        registry.service.revoke_credential(MEMBER, "t-1")


def test_a_member_cannot_tell_whether_someone_elses_token_exists(registry: Registry) -> None:
    add_token(registry, "admins", owner=ADMIN_ID)

    with pytest.raises(NotFound) as other:
        registry.service.revoke_credential(MEMBER, "admins")
    with pytest.raises(NotFound) as missing:
        registry.service.revoke_credential(MEMBER, "nothing")

    assert other.value.message == missing.value.message
    assert registry.state.credentials["admins"].revoked_at is None
    assert registry.service.revoke_credential(ADMIN, "admins") is True


def test_rotating_issues_a_successor_with_the_same_scopes_and_revokes_the_original(
    registry: Registry,
) -> None:
    add_token(registry, "t-1", scopes='["cards:read", "loops:read"]')
    registry.state.credentials["t-1"] = registry.state.credentials["t-1"].__replace__(
        name="x" * 200
    )

    issued = registry.service.rotate_credential(MEMBER, "t-1")

    assert issued["name"] == "x" * 180 + " (rotated)"
    assert issued["scopes"] == ["cards:read", "loops:read"]
    assert issued["owner_actor_id"] == MEMBER_ID
    days = registry.service.settings.member_token_default_days
    expected = (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert issued["expires_at"] == expected
    assert registry.state.credentials["t-1"].revoked_at == NOW_TEXT
    assert registry.state.actors["agent-t-1"].disabled_at == NOW_TEXT


def test_an_administrator_rotating_a_members_token_keeps_the_member_as_owner(
    registry: Registry,
) -> None:
    add_token(registry, "t-1")
    add_token(registry, "unowned", owner=None)

    rotated = registry.service.rotate_credential(ADMIN, "t-1")
    adopted = registry.service.rotate_credential(ADMIN, "unowned")

    assert (rotated["owner_actor_id"], rotated["owner_name"]) == (MEMBER_ID, "Ada")
    assert adopted["owner_actor_id"] == ADMIN_ID


def test_a_member_at_the_limit_cannot_rotate(registry: Registry) -> None:
    for index in range(registry.service.settings.member_token_limit):
        add_token(registry, f"t-{index}")

    with pytest.raises(Conflict):
        registry.service.rotate_credential(MEMBER, "t-0")

    assert registry.state.credentials["t-0"].revoked_at is None
