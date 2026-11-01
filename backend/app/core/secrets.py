"""Encrypted storage for provider credentials (API keys).

Keys are sealed with Fernet (AES-128-CBC + HMAC) using a key derived from the installation secret
through HKDF, so a copied `registry.sqlite` alone does not expose provider keys. Raw keys are never
returned by the API after submission; only a short hint is kept for display.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .security import MIN_SECRET_LENGTH, WEAK_SECRETS, resolve_secret_key

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


def fernet(settings) -> Fernet:  # noqa: ANN001 - avoids a config import cycle
    return _fernet_for(resolve_secret_key(settings))


def previous_fernet(settings) -> Fernet | None:  # noqa: ANN001
    """The key the installation used before its most recent secret change, when configured."""
    previous = (getattr(settings, "previous_secret_key", None) or "").strip()
    if not previous or previous in WEAK_SECRETS or len(previous) < MIN_SECRET_LENGTH:
        return None
    return _fernet_for(previous)


def seal_secret(settings, value: str) -> str:  # noqa: ANN001
    return fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def open_secret_state(settings, token: str) -> tuple[str, bool]:  # noqa: ANN001
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


def open_secret(settings, token: str) -> str:  # noqa: ANN001
    return open_secret_state(settings, token)[0]


def secret_hint(value: str | None) -> str | None:
    """A non-reversible display hint, for example ``••••ab12``."""
    if not value:
        return None
    return f"\u2022\u2022\u2022\u2022{value[-4:]}"
