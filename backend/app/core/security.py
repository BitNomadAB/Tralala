"""Password, token, session-cookie and CSRF primitives.

Only hashes of API tokens and passwords are persisted; raw values never touch the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path

from .platform import PROFILE_WINDOWS, resolve_profile

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

logger = logging.getLogger("tralala.security")

# Published default kept only so an upgraded deployment can be detected and repaired.
INSECURE_DEFAULT_SECRET = "dev-insecure-secret-change-me"
MIN_SECRET_LENGTH = 32
WEAK_SECRETS = frozenset(
    {
        INSECURE_DEFAULT_SECRET,
        "change-me-to-a-long-random-string",
        "change-me",
        "changeme",
        "secret",
        "secret-key",
        "test-secret",
    }
)
SECRET_FILE_NAME = ".session-secret"
BOOTSTRAP_PASSWORD_FILE_NAME = ".bootstrap-password"

# Shipped/placeholder values treated as "no password chosen".
# Values that must never become an administrator password. The last one is the shared test password
# this repository used to publish: an operator who copies an old .env still gets a generated one.
INSECURE_BOOTSTRAP_PASSWORDS = frozenset(
    {"admin", "password", "change-me", "changeme", "tralala-dev-1", ""}
)


SESSION_COOKIE = "tralala_session"
CSRF_COOKIE = "tralala_csrf"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    salt_b64 = base64.b64encode(salt).decode()
    digest_b64 = base64.b64encode(digest).decode()
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def generate_token() -> str:
    return "trl_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_value(secret: str, session_id: str, ttl_seconds: int) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl_seconds
    payload = f"{session_id}.{expires_at}"
    return f"{payload}.{_sign(secret, payload)}", expires_at


def read_session_value(secret: str, value: str) -> tuple[str, int] | None:
    """Return ``(session_id, expires_at)`` for a valid signed value, else ``None``."""
    parts = value.rsplit(".", 2)
    if len(parts) != 3:
        return None
    session_id, expires_raw, signature = parts
    payload = f"{session_id}.{expires_raw}"
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        return None
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None
    if expires_at < int(time.time()):
        return None
    return session_id, expires_at


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def write_private_file(path: Path, value: str) -> None:
    """Create or replace a file readable only by the owner, atomically enough for one process."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    if resolve_profile(None) == PROFILE_WINDOWS:  # pragma: no cover - exercised on Windows
        # NTFS has no permission bits: this would only clear the read-only flag, and the file's
        # protection comes from the ACL it inherits from its directory.
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def resolve_secret_key(settings) -> str:  # noqa: ANN001 - avoids a config import cycle
    """Return the session-signing secret, never a weak or published value.

    An explicit secret wins only when it is long enough and not a published placeholder. Otherwise
    a random secret is generated once and persisted with owner-only permissions under the data
    directory, so every install is unique and sessions survive restarts.
    """
    configured = (getattr(settings, "secret_key", None) or "").strip()
    if configured and configured not in WEAK_SECRETS and len(configured) >= MIN_SECRET_LENGTH:
        return configured
    if configured:
        logger.warning(
            "TRALALA_SECRET_KEY is a placeholder or shorter than %s characters; "
            "generating a per-install secret instead",
            MIN_SECRET_LENGTH,
        )
    settings.ensure_dirs()
    path = Path(settings.data_dir) / SECRET_FILE_NAME
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    value = secrets.token_urlsafe(48)
    write_private_file(path, value)
    logger.info("generated a per-install session secret at %s", path)
    return value
