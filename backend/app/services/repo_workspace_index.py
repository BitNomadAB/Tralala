"""The repository workspace's index: the text files of a run's commits, read once into memory.

A generation run that lets the model read the board's repositories (decision 0025) answers every
tool call from this index. It is built from the archives the run already fetched, one per
repository, and is pure: nothing here touches the disk, the network, a subprocess or a thread, and
a path is a key in a dict, never a file name.

What the index holds is what ``repo_snapshot.select_members`` keeps: the noise filter (build
output, dependencies, lock files, binary suffixes, empty files) and the board link's focus and
exclude globs, with the archive's first path segment dropped (GitHub's
``<owner>-<repository>-<sha>/``, the mirror's ``snapshot/``). Of those, only text is kept: a file
with a NUL byte is binary and left out without a trace, and text is decoded as UTF-8 with
replacement characters.

The workspace is bounded as a whole (``MAX_FILES`` files, ``MAX_TEXT_BYTES`` of text, at most
``MAX_FILE_BYTES`` per file), filled in the snapshot's priority order and repository by repository,
so the limits fall on the files an analysis needs least. A file that does not fit is skipped and
the next one still comes; it stays in the index without its text (``left_out``), so the model can
see that it exists. A repository whose archive cannot be read is a manifest entry with an error,
never an exception.
"""

from __future__ import annotations

import copy
import io
import logging
import tarfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from .repo_snapshot import select_members

logger = logging.getLogger("tralala.repo_workspace")

MAX_FILES: Final = 20_000
MAX_TEXT_BYTES: Final = 64 * 1024 * 1024
MAX_FILE_BYTES: Final = 8 * 1024 * 1024
# Files left out are listed by path and size up to this many; the rest are only counted.
MAX_LEFT_OUT_LISTED: Final = 5_000

type LeftOut = Literal["too_large", "workspace_full"]


class WorkspaceSource(NamedTuple):
    """One repository as a run fetched it: its name, the commit, the commit's gzip tarball and the
    board link's globs."""

    name: str
    commit_sha: str
    archive: bytes
    focus: Sequence[str] = ()
    exclude: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceFile:
    """One file of the index. ``path`` is ``<repository>/<relative>``; ``size`` is its bytes in the
    archive. A file the bounds left out has no text and names why in ``left_out``."""

    path: str
    repository: str
    relative: str
    size: int
    text: str
    left_out: LeftOut | None = None

    def lines(self) -> list[str]:
        """The text's lines as an editor numbers them: split at ``\\n``, a trailing ``\\r``
        dropped, no empty line after a final newline."""
        lines = self.text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return [line[:-1] if line.endswith("\r") else line for line in lines]


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryManifest:
    """What the workspace holds of one repository: its readable files and their bytes, the files
    the bounds left out, and the error when the archive could not be read."""

    name: str
    commit_sha: str
    files: int
    bytes: int
    left_out: int
    error: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceIndex:
    """Every file by path, sorted, every directory, and one manifest entry per repository."""

    files: dict[str, WorkspaceFile]
    directories: frozenset[str]
    repositories: tuple[RepositoryManifest, ...]
    # Left out and not even listed, because MAX_LEFT_OUT_LISTED was reached.
    unlisted: int


def clean_path(raw: str) -> str:
    """A path as the index keys it: forward slashes, no leading ``./`` or ``/``, no trailing
    ``/``; ``""`` and ``"."`` are the whole workspace. ``..`` is kept, and no key has it."""
    path = raw.strip().replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    while path.startswith("./"):
        path = path[2:]
    path = path.strip("/")
    return "" if path == "." else path


def _is_text(payload: bytes) -> bool:
    """The snapshot's rule (``repo_snapshot``): a NUL byte means binary."""
    return b"\x00" not in payload


def unique_name(name: str, taken: set[str]) -> str:
    """The repository's name as the first segment of its paths: no slash, never empty, and
    distinct from the names already taken (``app``, ``app-2``)."""
    clean = name.strip().replace("/", "-").replace("\\", "-")
    if clean in {"", ".", ".."}:
        clean = "repository"
    candidate = clean
    number = 2
    while candidate in taken:
        candidate = f"{clean}-{number}"
        number += 1
    taken.add(candidate)
    return candidate


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceLimits:
    """The workspace's bounds: readable files, bytes of text, bytes of one file, and how many
    files left out are still listed by path."""

    files: int = MAX_FILES
    text_bytes: int = MAX_TEXT_BYTES
    file_bytes: int = MAX_FILE_BYTES
    left_out_listed: int = MAX_LEFT_OUT_LISTED


@dataclass(slots=True)
class _Budget:
    """What the bounds still allow, shared by every repository of one workspace."""

    limits: WorkspaceLimits
    files: int = 0
    text_bytes: int = 0
    left_out_listed: int = 0
    unlisted: int = 0

    def refusal(self, size: int) -> LeftOut | None:
        if size > self.limits.file_bytes:
            return "too_large"
        if self.files >= self.limits.files or self.text_bytes + size > self.limits.text_bytes:
            return "workspace_full"
        return None


def _read_repository(
    source: WorkspaceSource, name: str, budget: _Budget
) -> tuple[list[WorkspaceFile], int]:
    """The files of one archive in priority order, and how many were left out of it; raises the
    archive's own error when it cannot be read."""
    files: list[WorkspaceFile] = []
    seen: set[str] = set()
    left_out = 0
    with tarfile.open(fileobj=io.BytesIO(source.archive), mode="r:gz") as archive:
        members = select_members(archive, focus=source.focus, exclude=source.exclude)
        for _priority, member, relative in members:
            if relative in seen or any(part in {".", ".."} for part in relative.split("/")):
                continue
            seen.add(relative)
            path = f"{name}/{relative}"
            refusal = budget.refusal(member.size)
            if refusal is not None:
                left_out += 1
                if budget.left_out_listed >= budget.limits.left_out_listed:
                    budget.unlisted += 1
                    continue
                budget.left_out_listed += 1
                files.append(
                    WorkspaceFile(
                        path=path,
                        repository=name,
                        relative=relative,
                        size=member.size,
                        text="",
                        left_out=refusal,
                    )
                )
                continue
            handle = archive.extractfile(member)
            payload = b"" if handle is None else handle.read()
            if not payload or not _is_text(payload):
                continue
            text = payload.decode("utf-8", errors="replace")
            files.append(
                WorkspaceFile(
                    path=path, repository=name, relative=relative, size=len(payload), text=text
                )
            )
            budget.files += 1
            budget.text_bytes += len(payload)
    return files, left_out


def _directories(paths: Sequence[str]) -> frozenset[str]:
    found: set[str] = set()
    for path in paths:
        parts = path.split("/")
        for end in range(1, len(parts)):
            found.add("/".join(parts[:end]))
    return frozenset(found)


def build_index(
    sources: Sequence[WorkspaceSource], limits: WorkspaceLimits | None = None
) -> WorkspaceIndex:
    """Read every archive into one index; an archive that cannot be read is an error entry."""
    budget = _Budget(limits or WorkspaceLimits())
    taken: set[str] = set()
    files: list[WorkspaceFile] = []
    repositories: list[RepositoryManifest] = []
    for source in sources:
        name = unique_name(source.name, taken)
        trial = copy.copy(budget)
        try:
            found, left_out = _read_repository(source, name, trial)
        except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
            # Nothing of a broken archive is kept: a partial repository would read as complete.
            logger.warning(
                "repository_workspace_unreadable",
                extra={"repository": name, "error": type(exc).__name__},
            )
            repositories.append(
                RepositoryManifest(
                    name=name,
                    commit_sha=source.commit_sha,
                    files=0,
                    bytes=0,
                    left_out=0,
                    error="malformed_archive",
                )
            )
            continue
        budget = trial
        files += found
        readable = [file for file in found if file.left_out is None]
        repositories.append(
            RepositoryManifest(
                name=name,
                commit_sha=source.commit_sha,
                files=len(readable),
                bytes=sum(file.size for file in readable),
                left_out=left_out,
            )
        )
    by_path = {file.path: file for file in sorted(files, key=lambda file: file.path)}
    logger.info(
        "repository_workspace_built",
        extra={
            "repositories": len(repositories),
            "files": budget.files,
            "text_bytes": budget.text_bytes,
            "left_out": sum(entry.left_out for entry in repositories),
        },
    )
    return WorkspaceIndex(
        files=by_path,
        directories=_directories(list(by_path)),
        repositories=tuple(repositories),
        unlisted=budget.unlisted,
    )
