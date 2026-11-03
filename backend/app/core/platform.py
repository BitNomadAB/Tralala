"""Host filesystem differences, behind one profile.

Deleting a file means two different things depending on the host. Windows refuses to remove a file
another process holds open (`WinError 32`), so an antivirus scanner or an indexer can make a board
deletion fail halfway. POSIX removes the name and keeps the open file alive as an anonymous inode,
so the same call succeeds and a write from elsewhere is lost silently. On a network filesystem a
removal can also fail transiently with `ENOTEMPTY`/`EBUSY`.

The mechanism that talks to the host is chosen by the real operating system, because guessing wrong
would break locking outright. What the profile decides is the *policy*: which errors are worth
retrying, and what an operator should expect when one is not. `TRALALA_PLATFORM_PROFILE` overrides
the detection for an image or a share (e.g. `network` for a board directory on NFS/SMB).
"""

from __future__ import annotations

import errno
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

PROFILE_AUTO = "auto"
PROFILE_POSIX = "posix"
PROFILE_WINDOWS = "windows"
PROFILE_NETWORK = "network"
PROFILES = (PROFILE_AUTO, PROFILE_POSIX, PROFILE_WINDOWS, PROFILE_NETWORK)

# WinError 32: another process holds the file. WinError 5: denied, which antivirus and the search
# indexer also raise while they hold a handle. WinError 145: the directory was not empty yet.
_WINDOWS_TRANSIENT = frozenset({5, 32, 145})
# POSIX never raises for an open file, but a network filesystem can still be briefly busy.
_POSIX_TRANSIENT = frozenset({errno.ENOTEMPTY, errno.EBUSY, errno.EAGAIN})

ATTEMPTS = 4
DELAY_SECONDS = 0.1


def resolve_profile(configured: str | None) -> str:
    """The profile in force: the configured value, or the operating system's own semantics."""
    value = (configured or PROFILE_AUTO).strip().lower()
    if value in (PROFILE_POSIX, PROFILE_WINDOWS, PROFILE_NETWORK):
        return value
    return PROFILE_WINDOWS if os.name == "nt" else PROFILE_POSIX


def lock_primitive() -> str:
    """Which file-locking library this host has.

    Deliberately *not* taken from the profile: a configuration mistake must never select a locking
    call the host does not have. The profile describes expectations, this describes reality.
    """
    return PROFILE_WINDOWS if os.name == "nt" else PROFILE_POSIX


def transient_error(exc: OSError, profile: str) -> str | None:
    """Why ``exc`` is worth retrying under ``profile``, or None when retrying cannot help.

    `EACCES`, `EPERM`, `EROFS` and a missing owner are never retried: nothing changes between two
    attempts, and a retry would only delay an error the operator has to fix.
    """
    if isinstance(exc, FileNotFoundError):
        return "already_gone"
    if profile == PROFILE_WINDOWS:
        code = getattr(exc, "winerror", None)
        if code in _WINDOWS_TRANSIENT:
            return f"winerror_{code}"
        return None
    if exc.errno in _POSIX_TRANSIENT:
        return errno.errorcode.get(exc.errno, str(exc.errno)).lower()
    return None


def retry_io(operation: str, profile: str, func: Callable[[], object]) -> None:
    """Run ``func`` and retry only the errors the host can clear on its own.

    Anything considered permanent (`EACCES`, `EPERM`, `EROFS`) raises immediately, because a second
    attempt would produce the same answer.
    """
    last: OSError | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            func()
        except OSError as exc:
            if transient_error(exc, profile) is None:
                raise
            last = exc
            if attempt < ATTEMPTS:
                time.sleep(DELAY_SECONDS)
        else:
            return
    raise last if last is not None else OSError(f"{operation} failed")


def remove_tree(path: Path | str, *, profile: str) -> None:
    """Remove a directory and everything in it, retrying only errors that can clear on their own."""
    target = Path(path)
    if not target.exists():
        return
    retry_io("remove_tree", profile, lambda: shutil.rmtree(target, ignore_errors=False))


def remove_file(path: Path | str, *, profile: str) -> bool:
    """Remove one file. Returns False when it was already gone, retrying transient locks."""
    target = Path(path)
    gone = False

    def unlink() -> None:
        nonlocal gone
        try:
            target.unlink()
        except FileNotFoundError:
            gone = True

    retry_io("remove_file", profile, unlink)
    return not gone


def replace_file(source: Path | str, destination: Path | str, *, profile: str) -> None:
    """Move a finished file into place atomically, retrying a transient Windows lock."""
    src, dst = Path(source), Path(destination)
    retry_io("replace_file", profile, lambda: src.replace(dst))


def copy_file(source: Path | str, destination: Path | str, *, profile: str) -> None:
    """Copy a file's content and metadata, retrying a host that holds the source briefly."""
    src, dst = Path(source), Path(destination)
    retry_io("copy_file", profile, lambda: shutil.copy2(src, dst))
