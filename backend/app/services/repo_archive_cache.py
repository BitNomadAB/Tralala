"""GitHub archives kept per repository and commit, so a second run on the same commit downloads
nothing.

A run of a GitHub repository resolves the branch to a commit and then needs that commit's tarball.
The tarball of a commit never changes, so it is kept under the repository's own directory,
``<data>/repos/<repository_id>/archive-<sha>.tar.gz``, beside the mirror a ``git_https`` repository
keeps there, and removed with it. ``TRALALA_REPOSITORY_ARCHIVE_CACHE_MAX_BYTES`` bounds the cache
across all repositories: after a new archive is stored, the oldest are removed until the total fits.
It is a cache, not data: losing it costs one download, and a failure to read or write it is logged
and never fails a run.

``ArchiveCache`` decides; :class:`ArchiveFiles` is the disk, so the rules run in a unit test on fake
files. ``ArchiveFilesOnDisk`` is the real directory.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

logger = logging.getLogger("tralala.repo_snapshot")

DEFAULT_MAX_BYTES: Final = 256 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
_NAME = re.compile(r"archive-(?P<sha>[0-9a-f]{40}|[0-9a-f]{64})\.tar\.gz")


@dataclass(frozen=True, slots=True)
class CachedArchive:
    """One stored archive: whose, which commit, how large and when it was written."""

    repository_id: str
    sha: str
    size: int
    written: float


class ArchiveFiles(Protocol):
    """The cache's files: one archive per repository and commit."""

    def read(self, repository_id: str, sha: str) -> bytes | None:
        """The archive, or None when there is none."""
        ...

    def write(self, repository_id: str, sha: str, data: bytes) -> None: ...

    def entries(self) -> list[CachedArchive]:
        """Every stored archive, in no particular order."""
        ...

    def remove(self, repository_id: str, sha: str) -> None:
        """Remove the archive; one that is already gone is fine."""
        ...


def cache_key_valid(repository_id: str, sha: str) -> bool:
    """A repository id and a commit that are safe as a directory and a file name."""
    return bool(_ID.fullmatch(repository_id)) and bool(_SHA.fullmatch(sha))


class ArchiveCache:
    """Archives by repository and commit, at most ``max_bytes`` together, the oldest out first."""

    def __init__(self, files: ArchiveFiles, *, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.files = files
        self.max_bytes = max_bytes

    def get(self, repository_id: str, sha: str) -> bytes | None:
        if self.max_bytes <= 0 or not cache_key_valid(repository_id, sha):
            return None
        try:
            return self.files.read(repository_id, sha)
        except OSError as exc:
            _log_failure("read", repository_id, exc)
            return None

    def put(self, repository_id: str, sha: str, data: bytes) -> None:
        """Keep ``data``, then remove the oldest archives until the cache fits; an archive larger
        than the whole cache is not kept."""
        if len(data) > self.max_bytes or not cache_key_valid(repository_id, sha):
            return
        try:
            self.files.write(repository_id, sha, data)
            self._evict(keep=(repository_id, sha))
        except OSError as exc:
            _log_failure("write", repository_id, exc)

    def _evict(self, *, keep: tuple[str, str]) -> None:
        entries = sorted(self.files.entries(), key=lambda entry: (entry.written, entry.sha))
        total = sum(entry.size for entry in entries)
        for entry in entries:
            if total <= self.max_bytes:
                return
            if (entry.repository_id, entry.sha) == keep:
                continue
            self.files.remove(entry.repository_id, entry.sha)
            total -= entry.size
            logger.info(
                "repository_archive_evicted",
                extra={"repository_id": entry.repository_id, "commit_sha": entry.sha},
            )


def _log_failure(operation: str, repository_id: str, exc: OSError) -> None:
    logger.warning(
        "repository_archive_cache_failed",
        extra={
            "operation": operation,
            "repository_id": repository_id,
            "error": type(exc).__name__,
        },
    )


class ArchiveFilesOnDisk:
    """The real files: ``<repos>/<repository_id>/archive-<sha>.tar.gz``."""

    def __init__(self, repos_dir: Path) -> None:
        self.repos_dir = repos_dir

    def _path(self, repository_id: str, sha: str) -> Path:
        return self.repos_dir / repository_id / f"archive-{sha}.tar.gz"

    def read(self, repository_id: str, sha: str) -> bytes | None:
        path = self._path(repository_id, sha)
        return path.read_bytes() if path.is_file() else None

    def write(self, repository_id: str, sha: str, data: bytes) -> None:
        path = self._path(repository_id, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        partial.write_bytes(data)
        partial.replace(path)

    def entries(self) -> list[CachedArchive]:
        found: list[CachedArchive] = []
        if not self.repos_dir.is_dir():
            return found
        for path in self.repos_dir.glob("*/archive-*.tar.gz"):
            match = _NAME.fullmatch(path.name)
            if match is None or not path.is_file():
                continue
            stat = path.stat()
            found.append(
                CachedArchive(path.parent.name, match.group("sha"), stat.st_size, stat.st_mtime)
            )
        return found

    def remove(self, repository_id: str, sha: str) -> None:
        self._path(repository_id, sha).unlink(missing_ok=True)
