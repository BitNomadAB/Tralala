"""The files of the Git mirrors, behind a Protocol so the mirror service never touches a disk.

Each repository read through the provider ``git_https`` has one directory,
``<data>/repos/<repository_id>/``, holding the bare mirror ``mirror.git`` and ``state.json`` (the
URL without credentials, the branch, the default branch, the last commit, when it was fetched, the
size after hygiene and the last error). Nothing else is written there. The directory is a cache:
backups leave it out, and deleting it costs one clone on the next run.

:class:`DiskMirrorFiles` is the real implementation. The repository id is the only text that
reaches a path, and it is accepted only as a canonical UUID; removal goes through the platform's
``remove_tree`` with its retry profile. A unit test uses an in-memory fake instead.
"""

from __future__ import annotations

import json
import stat
import uuid
from pathlib import Path
from typing import Final, Protocol, TypedDict

from pydantic import JsonValue

from ..core.platform import remove_tree, replace_file

MIRROR_DIR: Final = "mirror.git"
STATE_FILE: Final = "state.json"
_STATE_PART: Final = "state.json.part"


class MirrorState(TypedDict):
    """``state.json``: what the last good fetch left, and why the last one failed, if it did."""

    url: str
    branch: str
    default_branch: str | None
    last_sha: str | None
    fetched_at: str | None
    mirror_bytes: int | None
    last_error: str | None


class MirrorFiles(Protocol):
    """Where a repository's mirror is and what is known about it."""

    def mirror_path(self, repository_id: str) -> str:
        """The bare mirror's directory, as git takes it on its command line."""
        ...

    def has_mirror(self, repository_id: str) -> bool:
        """Whether a mirror is there (a clone that finished)."""
        ...

    def prepare(self, repository_id: str) -> None:
        """Create the repository's directory, so a clone can write ``mirror.git`` into it."""
        ...

    def size(self, repository_id: str) -> int:
        """The bytes the repository's directory takes, mirror and state together."""
        ...

    def read_state(self, repository_id: str) -> MirrorState | None:
        """``state.json``, or None when it is missing or cannot be read as one."""
        ...

    def write_state(self, repository_id: str, state: MirrorState) -> None:
        """Replace ``state.json`` as a whole."""
        ...

    def remove(self, repository_id: str) -> None:
        """Remove the repository's directory; ``OSError`` when the host still holds a file in it
        after the platform's retries. A directory that is not there is already removed."""
        ...

    def repository_ids(self) -> list[str]:
        """The repositories that have a directory, so a sweep can find the ones without a row."""
        ...


# --- state.json -----------------------------------------------------------------------------------


def encode_state(state: MirrorState) -> bytes:
    """``state.json`` as written: UTF-8, LF, the same bytes on every platform."""
    return (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) and value else None


def decode_state(raw: bytes) -> MirrorState | None:
    """``state.json`` read back; anything that is not one is None, so the mirror is cloned again."""
    try:
        parsed: JsonValue = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    url, branch = _text(parsed.get("url")), _text(parsed.get("branch"))
    if url is None or branch is None:
        return None
    size = parsed.get("mirror_bytes")
    return {
        "url": url,
        "branch": branch,
        "default_branch": _text(parsed.get("default_branch")),
        "last_sha": _text(parsed.get("last_sha")),
        "fetched_at": _text(parsed.get("fetched_at")),
        "mirror_bytes": size if isinstance(size, int) and not isinstance(size, bool) else None,
        "last_error": _text(parsed.get("last_error")),
    }


def canonical_repository_id(repository_id: str) -> str | None:
    """The id as the canonical UUID text the registry stores, or None for anything else."""
    try:
        canonical = str(uuid.UUID(repository_id))
    except ValueError:
        return None
    return canonical if canonical == repository_id else None


# --- the real files -------------------------------------------------------------------------------


class DiskMirrorFiles:
    """The mirrors under ``root`` (``<data>/repos``), removed with the host's retry ``profile``."""

    def __init__(self, root: Path, *, profile: str) -> None:
        self.root = root
        self.profile = profile

    def _directory(self, repository_id: str) -> Path:
        canonical = canonical_repository_id(repository_id)
        if canonical is None:
            raise ValueError("a repository id is a canonical UUID")
        return self.root / canonical

    def mirror_path(self, repository_id: str) -> str:
        return str(self._directory(repository_id) / MIRROR_DIR)

    def has_mirror(self, repository_id: str) -> bool:
        return (self._directory(repository_id) / MIRROR_DIR / "HEAD").is_file()

    def prepare(self, repository_id: str) -> None:
        self._directory(repository_id).mkdir(parents=True, exist_ok=True)

    def size(self, repository_id: str) -> int:
        directory = self._directory(repository_id)
        if not directory.is_dir():
            return 0
        total = 0
        for folder, _directories, files in directory.walk(follow_symlinks=False):
            total += sum((folder / name).lstat().st_size for name in files)
        return total

    def read_state(self, repository_id: str) -> MirrorState | None:
        path = self._directory(repository_id) / STATE_FILE
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        return decode_state(raw)

    def write_state(self, repository_id: str, state: MirrorState) -> None:
        directory = self._directory(repository_id)
        directory.mkdir(parents=True, exist_ok=True)
        part = directory / _STATE_PART
        part.write_bytes(encode_state(state))
        replace_file(part, directory / STATE_FILE, profile=self.profile)

    def remove(self, repository_id: str) -> None:
        directory = self._directory(repository_id)
        if not directory.exists():
            return
        # Git writes its packs read-only; Windows refuses to delete a read-only file.
        for folder, _directories, files in directory.walk(follow_symlinks=False):
            for name in files:
                path = folder / name
                mode = path.lstat().st_mode
                if not stat.S_ISLNK(mode) and not mode & stat.S_IWRITE:
                    path.chmod(mode | stat.S_IWRITE)
        remove_tree(directory, profile=self.profile)

    def repository_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and canonical_repository_id(entry.name) is not None
        )
