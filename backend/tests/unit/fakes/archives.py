"""The archive cache's files in memory: what was written, in which order, and failures on demand."""

from __future__ import annotations

from app.services.repo_archive_cache import CachedArchive


class FakeArchiveFiles:
    """``ArchiveFiles`` over a dict; each write is one tick later than the one before."""

    def __init__(self, *, fail: str | None = None) -> None:
        self.stored: dict[tuple[str, str], tuple[bytes, float]] = {}
        self.removed: list[tuple[str, str]] = []
        self.fail = fail
        self._tick = 0.0

    def read(self, repository_id: str, sha: str) -> bytes | None:
        if self.fail == "read":
            raise PermissionError("read refused")
        found = self.stored.get((repository_id, sha))
        return None if found is None else found[0]

    def write(self, repository_id: str, sha: str, data: bytes) -> None:
        if self.fail == "write":
            raise OSError("disk full")
        self._tick += 1
        self.stored[(repository_id, sha)] = (data, self._tick)

    def entries(self) -> list[CachedArchive]:
        return [
            CachedArchive(repository_id, sha, len(data), written)
            for (repository_id, sha), (data, written) in self.stored.items()
        ]

    def remove(self, repository_id: str, sha: str) -> None:
        self.stored.pop((repository_id, sha), None)
        self.removed.append((repository_id, sha))
