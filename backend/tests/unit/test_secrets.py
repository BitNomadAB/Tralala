"""Sealed provider credentials: a key comes back out only with the secret that sealed it."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.secrets import (
    CredentialError,
    open_secret,
    open_secret_state,
    previous_fernet,
    seal_secret,
    secret_hint,
)

CURRENT = "current-installation-secret-" + "c" * 24
PREVIOUS = "previous-installation-secret-" + "p" * 24
KEY = "sk-provider-key-1234"

# Sealed once by an earlier build with the secret below. Opening it proves the key derivation (salt,
# info, HKDF parameters) never changed: a change would lock every installation out of its keys.
EARLIER_SECRET = "sealed-by-an-earlier-install-" + "e" * 20
EARLIER_TOKEN = (
    "gAAAAABq6UX0iT0eisTSRw_buIakoJrmQ3Rj9SPNFy2LzoQmkmIbmm-F8S12zMtdO-QYQfc_VFATi2sc0IJZs7mb1bs"
    "ORRUgZ2dXvjLmz0twQSX8Mz-aPAQ="
)


def _with(settings: Settings, secret: str, previous: str | None = None) -> Settings:
    return settings.model_copy(update={"secret_key": secret, "previous_secret_key": previous})


def test_a_sealed_key_opens_with_the_same_secret(settings: Settings) -> None:
    current = _with(settings, CURRENT)
    sealed = seal_secret(current, KEY)
    assert KEY not in sealed
    assert open_secret(current, sealed) == KEY
    assert open_secret_state(current, sealed) == (KEY, True)


def test_sealing_twice_gives_two_ciphertexts_for_one_key(settings: Settings) -> None:
    current = _with(settings, CURRENT)
    first, second = seal_secret(current, KEY), seal_secret(current, KEY)
    assert first != second
    assert open_secret(current, first) == open_secret(current, second) == KEY


def test_a_key_sealed_by_an_earlier_build_still_opens(settings: Settings) -> None:
    assert open_secret(_with(settings, EARLIER_SECRET), EARLIER_TOKEN) == "sk-provider-key-1234"


def test_another_secret_cannot_open_the_key(settings: Settings) -> None:
    sealed = seal_secret(_with(settings, PREVIOUS), KEY)
    with pytest.raises(CredentialError):
        open_secret(_with(settings, CURRENT), sealed)


def test_the_previous_secret_opens_a_key_and_says_it_needs_resealing(settings: Settings) -> None:
    sealed = seal_secret(_with(settings, PREVIOUS), KEY)
    assert open_secret_state(_with(settings, CURRENT, PREVIOUS), sealed) == (KEY, False)


@pytest.mark.parametrize("previous", [None, "", "   ", "test-secret", "too-short-to-be-a-secret"])
def test_a_weak_or_missing_previous_secret_is_never_used(
    settings: Settings, previous: str | None
) -> None:
    rotated = _with(settings, CURRENT, previous)
    assert previous_fernet(rotated) is None


@pytest.mark.parametrize("token", ["", "not-a-sealed-value", "gAAAAAB-truncated", "été"])
def test_a_corrupt_value_is_reported_not_returned(settings: Settings, token: str) -> None:
    with pytest.raises(CredentialError):
        open_secret(_with(settings, CURRENT, PREVIOUS), token)


@pytest.mark.parametrize(
    ("value", "hint"),
    [
        ("sk-provider-key-1234", "••••1234"),
        ("ab", "••••ab"),
        ("", None),
        (None, None),
    ],
)
def test_the_hint_shows_at_most_the_last_four_characters(
    value: str | None, hint: str | None
) -> None:
    assert secret_hint(value) == hint
    assert secret_hint(value) == hint
