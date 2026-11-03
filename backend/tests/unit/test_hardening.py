"""Secrets, passwords, tokens, sessions and CSRF: the primitives every sign-in rests on."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import security
from app.core.config import Settings
from app.core.errors import ValidationFailure
from app.core.security import (
    INSECURE_BOOTSTRAP_PASSWORDS,
    INSECURE_DEFAULT_SECRET,
    SECRET_FILE_NAME,
    WEAK_SECRETS,
    create_session_value,
    csrf_satisfied,
    generate_token,
    hash_password,
    hash_token,
    read_session_value,
    resolve_secret_key,
    verify_password,
)
from app.services.auth import check_password
from app.services.idempotency import request_fingerprint

PASSWORD = "correct horse battery staple"
SESSION_SECRET = "session-signing-secret-" + "k" * 24
NOW = 1_800_000_000


# --- the installation secret --------------------------------------------------------------------


def test_secret_is_generated_once_per_install(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key=None)
    first = resolve_secret_key(settings)
    second = resolve_secret_key(settings)
    assert first == second
    assert first != INSECURE_DEFAULT_SECRET
    assert len(first) >= 32
    secret_file = settings.data_dir / SECRET_FILE_NAME
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8").strip() == first


def test_published_default_secret_is_replaced(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key=INSECURE_DEFAULT_SECRET)
    resolved = resolve_secret_key(settings)
    assert resolved != INSECURE_DEFAULT_SECRET
    assert (settings.data_dir / SECRET_FILE_NAME).exists()


def test_explicit_secret_wins(tmp_path: Path) -> None:
    secret = "explicit-test-secret-with-enough-length"
    settings = Settings(data_dir=tmp_path / "data", secret_key=secret)
    assert resolve_secret_key(settings) == secret
    assert not (settings.data_dir / SECRET_FILE_NAME).exists()


def test_short_explicit_secret_is_replaced(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", secret_key="short-secret")
    resolved = resolve_secret_key(settings)
    assert resolved != "short-secret"
    assert (settings.data_dir / SECRET_FILE_NAME).exists()


def test_the_published_placeholders_count_as_weak() -> None:
    assert {INSECURE_DEFAULT_SECRET, "test-secret", "change-me"} <= WEAK_SECRETS


def test_the_shipped_bootstrap_password_never_becomes_a_real_one() -> None:
    """A copied old `.env` or the default must give a generated password, never a known one."""
    shipped = Settings.model_fields["bootstrap_password"].default
    assert shipped in INSECURE_BOOTSTRAP_PASSWORDS
    assert {"admin", "tralala-dev-1", ""} <= INSECURE_BOOTSTRAP_PASSWORDS


# --- passwords ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stored_hash() -> str:
    """One scrypt hash for the module: hashing is deliberately slow."""
    return hash_password(PASSWORD)


def test_a_password_verifies_against_its_own_hash_only(stored_hash: str) -> None:
    assert verify_password(PASSWORD, stored_hash) is True
    assert verify_password(PASSWORD, stored_hash) is True
    assert verify_password(PASSWORD + " ", stored_hash) is False
    assert verify_password(PASSWORD.upper(), stored_hash) is False
    assert verify_password("", stored_hash) is False


def test_the_stored_hash_names_its_parameters_and_hides_the_password(stored_hash: str) -> None:
    scheme, n, r, p, salt, digest = stored_hash.split("$")
    assert (scheme, n, r, p) == ("scrypt", "16384", "8", "1")
    assert salt and digest
    assert PASSWORD not in stored_hash


def test_the_same_password_is_salted_differently_each_time(stored_hash: str) -> None:
    again = hash_password(PASSWORD)
    assert again != stored_hash
    assert verify_password(PASSWORD, again) is True


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "plain-text-password",
        "bcrypt$1$2$3$c2FsdA==$ZGlnZXN0",
        "scrypt$x$8$1$c2FsdA==$ZGlnZXN0",
        "scrypt$16384$8$1$!!!$???",
        "scrypt$16384$8$1$c2FsdA==$",
    ],
)
def test_a_malformed_stored_hash_never_verifies(stored: str) -> None:
    assert verify_password("anything", stored) is False


@pytest.mark.parametrize(
    ("password", "username"),
    [
        ("seven77", None),
        ("password", None),
        ("PASSWORD", None),
        ("12345678", None),
        (" changeme ", None),
        ("Alice-The-Admin", "alice-the-admin"),
    ],
)
def test_a_weak_password_is_refused(
    settings: Settings, password: str, username: str | None
) -> None:
    with pytest.raises(ValidationFailure):
        check_password(
            password, minimum_length=settings.password_min_length, username=username
        )


def test_an_eight_character_password_is_accepted(settings: Settings) -> None:
    check_password("k3ttle!x", minimum_length=settings.password_min_length, username="alice")


def test_a_configured_minimum_below_eight_is_raised_to_eight() -> None:
    with pytest.raises(ValidationFailure) as refused:
        check_password("k3ttle!", minimum_length=4)
    assert refused.value.details == {"minimum_length": 8}


# --- API tokens ---------------------------------------------------------------------------------


def test_a_token_is_prefixed_and_never_repeats() -> None:
    first, second = generate_token(), generate_token()
    assert first.startswith("trl_") and second.startswith("trl_")
    assert first != second


def test_a_token_is_stored_only_as_a_stable_digest() -> None:
    """Every stored token is looked up by this digest, so it must never change between releases."""
    expected = "7aea120e5baaf5f2fdfbef35d8b9e3ce1ac39e490f45e5b9fc7f43eae2eeb200"
    assert hash_token("trl_example") == expected
    assert hash_token("trl_example") == expected
    assert hash_token("trl_other") != expected


# --- session cookies ----------------------------------------------------------------------------


def _freeze(monkeypatch: pytest.MonkeyPatch, now: int) -> None:
    monkeypatch.setattr(security, "time", SimpleNamespace(time=lambda: now))


def test_a_session_value_round_trips_until_it_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, NOW)
    value, expires_at = create_session_value(SESSION_SECRET, "session-1", 3600)
    assert expires_at == NOW + 3600
    assert create_session_value(SESSION_SECRET, "session-1", 3600) == (value, expires_at)
    assert read_session_value(SESSION_SECRET, value) == ("session-1", NOW + 3600)

    _freeze(monkeypatch, NOW + 3600)
    assert read_session_value(SESSION_SECRET, value) == ("session-1", NOW + 3600)
    _freeze(monkeypatch, NOW + 3601)
    assert read_session_value(SESSION_SECRET, value) is None


def test_a_session_value_from_another_installation_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, NOW)
    value, _ = create_session_value(SESSION_SECRET, "session-1", 3600)
    assert read_session_value("another-installation-secret-" + "x" * 20, value) is None


def test_a_tampered_session_value_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, NOW)
    value, _ = create_session_value(SESSION_SECRET, "session-1", 3600)
    session_id, expires, signature = value.rsplit(".", 2)
    assert read_session_value(SESSION_SECRET, f"session-2.{expires}.{signature}") is None
    assert read_session_value(SESSION_SECRET, f"{session_id}.{NOW + 99999}.{signature}") is None
    assert read_session_value(SESSION_SECRET, f"{session_id}.{expires}.{'0' * 64}") is None
    assert read_session_value(SESSION_SECRET, "no-dots-at-all") is None
    assert read_session_value(SESSION_SECRET, "") is None


def test_a_signed_value_with_a_broken_expiry_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, NOW)
    payload = "session-1.tomorrow"
    signature = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert read_session_value(SESSION_SECRET, f"{payload}.{signature}") is None


# --- CSRF double submit -------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_a_safe_method_needs_no_csrf_token(method: str) -> None:
    assert csrf_satisfied(method, "", "") is True


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    ("header", "cookie", "expected"),
    [
        ("token-value", "token-value", True),
        ("", "token-value", False),
        ("token-value", "", False),
        ("", "", False),
        ("token-value", "token-valuf", False),
        ("token-value ", "token-value", False),
    ],
)
def test_a_write_needs_the_header_to_repeat_the_cookie(
    method: str, header: str, cookie: str, expected: bool
) -> None:
    assert csrf_satisfied(method, header, cookie) is expected


# --- idempotency --------------------------------------------------------------------------------


def test_a_replayed_request_has_the_same_fingerprint_whatever_the_key_order() -> None:
    first = request_fingerprint({"title": "Ticket", "labels": ["a"], "list_id": "l1"})
    second = request_fingerprint({"list_id": "l1", "labels": ["a"], "title": "Ticket"})
    assert first == second
    assert len(first) == 64


def test_a_changed_payload_has_another_fingerprint() -> None:
    assert request_fingerprint({"title": "Ticket"}) != request_fingerprint({"title": "Ticket 2"})
    ordered = request_fingerprint({"labels": ["a", "b"]})
    assert ordered != request_fingerprint({"labels": ["b", "a"]})
