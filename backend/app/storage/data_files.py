"""The data directory's own files, on disk (``repositories/data_files.py`` is the Protocol)."""

from __future__ import annotations

from pathlib import Path

from ..core.platform import remove_file
from ..core.security import BOOTSTRAP_PASSWORD_FILE_NAME


class BootstrapPasswordFileOnDisk:
    """``<data>/.bootstrap-password``; the path is fixed, so no caller names a file."""

    def __init__(self, data_dir: Path, *, profile: str) -> None:
        self.path = Path(data_dir) / BOOTSTRAP_PASSWORD_FILE_NAME
        self._profile = profile

    def present(self) -> bool:
        return self.path.is_file()

    def remove(self) -> bool:
        # A virus scanner or an indexer may hold the file for a moment on Windows: the profile
        # retries what the host clears on its own and raises what it does not.
        return remove_file(self.path, profile=self._profile)
