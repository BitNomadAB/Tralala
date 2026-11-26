"""Encrypted storage for provider credentials (API keys).

Keys are sealed with Fernet (AES-128-CBC + HMAC) using a key derived from the installation secret
through HKDF, so a copied `registry.sqlite` alone does not expose provider keys. Raw keys are never
returned by the API after submission; only a short hint is kept for display.

The same sealing, under a key derived for one named purpose, protects a value that leaves the
installation and must come back unchanged (``seal_for_purpose``): the state of a question a key asks
its person (``services/request_state.py``).
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .security import MIN_SECRET_LENGTH, WEAK_SECRETS, resolve_secret_key

if TYPE_CHECKING:  # annotation only: config is not imported at run time
    from .config import Settings

# Frozen key-derivation material, not a brand name. Changing these bytes would make every
# credential sealed by an earlier install undecryptable, so they stay as shipped.
_INFO = b"kanban-agent-credentials-v1"


class CredentialError(Exception):
    """Raised when a stored credential cannot be opened (wrong secret or corrupt value)."""


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"kanban-agent-credentials",
        info=_INFO,
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def fernet(settings: Settings) -> Fernet:
    return _fernet_for(resolve_secret_key(settings))


def previous_fernet(settings: Settings) -> Fernet | None:
    """The key the installation used before its most recent secret change, when configured."""
    previous = (getattr(settings, "previous_secret_key", None) or "").strip()
    if not previous or previous in WEAK_SECRETS or len(previous) < MIN_SECRET_LENGTH:
        return None
    return _fernet_for(previous)


def seal_secret(settings: Settings, value: str) -> str:
    return fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def open_secret_state(settings: Settings, token: str) -> tuple[str, bool]:
    """Return ``(value, sealed_with_current_key)``; the previous secret is only a fallback."""
    try:
        return fernet(settings).decrypt(token.encode("ascii")).decode("utf-8"), True
    except (InvalidToken, ValueError):
        pass
    previous = previous_fernet(settings)
    if previous is not None:
        try:
            return previous.decrypt(token.encode("ascii")).decode("utf-8"), False
        except (InvalidToken, ValueError):
            pass
    raise CredentialError("Stored credential cannot be decrypted")


def open_secret(settings: Settings, token: str) -> str:
    return open_secret_state(settings, token)[0]


class SealedValueError(Exception):
    """Raised when a value sealed for a purpose cannot be opened: changed, malformed, sealed with
    another secret or for another purpose."""


# The salt of every purpose key. The purpose itself is the HKDF info, so each purpose gets a key of
# its own, and none of them is the provider-credential key above (another salt and info).
_PURPOSE_SALT = b"tralala-sealed-value"


@lru_cache(maxsize=8)
def _purpose_fernet(secret: str, purpose: str) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_PURPOSE_SALT,
        info=purpose.encode("utf-8"),
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def seal_for_purpose(secret: str, purpose: str, value: bytes) -> str:
    """Seal ``value`` (encrypted and authenticated) under a key derived from the installation
    secret for ``purpose`` alone; only :func:`open_for_purpose` with both again opens it."""
    return _purpose_fernet(secret, purpose).encrypt(value).decode("ascii")


def open_for_purpose(secret: str, purpose: str, token: str) -> bytes:
    """The value :func:`seal_for_purpose` sealed, or :class:`SealedValueError`."""
    try:
        return _purpose_fernet(secret, purpose).decrypt(token.encode("ascii"))
    except (InvalidToken, ValueError) as exc:  # UnicodeEncodeError is a ValueError
        raise SealedValueError("Sealed value cannot be opened") from exc


def secret_hint(value: str | None) -> str | None:
    """A non-reversible display hint, for example ``••••ab12``."""
    if not value:
        return None
    return f"\u2022\u2022\u2022\u2022{value[-4:]}"
