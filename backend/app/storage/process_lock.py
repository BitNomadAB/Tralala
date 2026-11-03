"""One backend process per data directory.

Per-board locks, the rate limiter and the per-install session secret are process-local, so a second
process on the same directory can race a schema rebuild while the first one is serving. The lock is
an operating-system file lock: the kernel drops it when the process dies, so a crash never leaves a
stale lock behind, and the file only carries the owner's pid to make the message actionable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO

from ..core.platform import PROFILE_WINDOWS, lock_primitive

LOCK_FILE_NAME = ".process.lock"

# ``lock_primitive`` chooses the locking call, and it names Windows exactly where ``sys.platform``
# is "win32". The lock calls test both: the second test is the one pyright evaluates statically, so
# the module, checked as Linux, does not look up ``msvcrt.locking``, which Linux's stub lacks.


class DataDirectoryLock:
    """Exclusive, non-blocking lock on one data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / LOCK_FILE_NAME
        self._handle: IO[bytes] | None = None

    def _lock_error(self, owner: str) -> RuntimeError:
        return RuntimeError(
            "This data directory is already in use by another Tralala process"
            f"{f' (pid {owner})' if owner else ''} at {self.path.parent}. "
            "Tralala expects exactly one backend process per data directory, because the per-board "
            "locks, the rate limiter and the session secret live in that process. "
            "Stop the other process, or point TRALALA_DATA_DIR at a different directory."
        )

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The handle is held for the process lifetime, so no context manager.
        handle = self.path.open("a+b")
        try:
            handle.seek(0)
            if lock_primitive() == PROFILE_WINDOWS and sys.platform == "win32":  # pragma: no cover
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            owner = ""
            try:
                handle.seek(0)
                owner = handle.read().decode("utf-8", "replace").strip()
            except OSError:
                owner = ""
            handle.close()
            raise self._lock_error(owner) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode())
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            handle.seek(0)
            if lock_primitive() == PROFILE_WINDOWS and sys.platform == "win32":  # pragma: no cover
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
