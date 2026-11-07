"""Which files of a repository archive a snapshot considers, in which order, and their manifest.

The noise filter (build output, dependencies, lock files, binaries), the board link's focus and
exclude globs and the priority order decide what ``repo_snapshot.read_snapshot`` reads. The
manifest names every file they keep, with its size and whether its content was sent, so a run that
could not send a file still knows the file exists. Everything here is pure: a tar index in, lists
out; nothing is extracted.
"""

from __future__ import annotations

import io
import json
import tarfile
import zlib
from collections.abc import Collection, Sequence
from fnmatch import fnmatchcase
from typing import TypedDict

from .repository_problems import EMPTY_ARCHIVE, NOTHING_READABLE, PATHS_MATCH_NOTHING

# Directories that never inform an analysis: build output, dependencies, caches.
SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        "__pycache__",
        "target",
        "vendor",
    }
)
# Lock files are generated, huge, and say nothing an analysis can use.
SKIPPED_NAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "composer.lock",
        "Gemfile.lock",
        "go.sum",
    }
)
SKIPPED_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tif", ".tiff", ".svgz",
        ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".jar", ".war", ".whl",
        ".so", ".dll", ".exe", ".dylib", ".bin", ".o", ".a", ".class", ".pyc", ".pyo",
        ".mp3", ".mp4", ".mov", ".wav", ".woff", ".woff2", ".ttf", ".otf",
        ".sqlite", ".sqlite3", ".db", ".parquet", ".pkl", ".onnx", ".pt", ".safetensors",
    }
)
# What an analysis asks first: the request, the rules, the documentation, then the entry points.
ROOT_DOC_PRIORITY = 0
DOCS_PRIORITY = 1
CONFIG_PRIORITY = 2
SOURCE_PRIORITY = 3
CONFIG_NAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        "Cargo.toml",
        "go.mod",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "Makefile",
        "tsconfig.json",
        "vite.config.ts",
        "vite.config.js",
        "alembic.ini",
        ".env.example",
    }
)
MAX_MANIFEST_ENTRIES = 5_000
"""The most files a manifest lists; ``manifest_omitted`` counts the rest."""

type Selected = tuple[tuple[int, int, str], tarfile.TarInfo, str]
"""A file ``select_members`` keeps: its priority key, its tar member, its path below the root."""


class ManifestEntry(TypedDict):
    """One file of the repository as the manifest lists it: its path below the root, its size and
    whether its content is among the snapshot's files."""

    path: str
    bytes: int
    sent: bool


def _priority(relative: str, depth: int) -> tuple[int, int, str]:
    name = relative.rsplit("/", 1)[-1]
    if depth == 1 and (name.upper().startswith("README") or name == "AGENTS.md"):
        return (ROOT_DOC_PRIORITY, 0, relative)
    if relative.startswith("docs/"):
        return (DOCS_PRIORITY, depth, relative)
    if depth == 1 and (name in CONFIG_NAMES or name.endswith((".toml", ".json", ".yml", ".yaml"))):
        return (CONFIG_PRIORITY, depth, relative)
    return (SOURCE_PRIORITY, depth, relative)


def path_selected(relative: str, focus: Sequence[str], exclude: Sequence[str]) -> bool:
    """Whether a board link's globs keep a file: one an exclude glob matches is dropped, and when
    there are focus globs only a file one of them matches is kept.

    ``relative`` is the POSIX path below the repository root. The match is ``fnmatchcase``: case
    sensitive on every platform, and its ``*`` matches ``/`` too, so ``docs/*`` covers every file
    below ``docs/`` and ``*.md`` every Markdown file at any depth.
    """
    if any(fnmatchcase(relative, glob) for glob in exclude):
        return False
    return not focus or any(fnmatchcase(relative, glob) for glob in focus)


def select_members(
    archive: tarfile.TarFile,
    *,
    focus: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> list[Selected]:
    """Everything worth reading, ordered so the same SHA always yields the same prompt.

    Noise (build output, dependencies, lock files, binaries) is skipped first, then the link's
    globs choose among the rest (``path_selected``), and only then is the result put in priority
    order, so the caps fall on the files the globs kept.
    """
    selected: list[Selected] = []
    for member in archive.getmembers():
        if not member.isfile() or member.size <= 0:
            continue
        parts = [segment for segment in member.name.split("/") if segment]
        if len(parts) < 2:
            continue
        # GitHub wraps everything in `<owner>-<repository>-<sha>/`; drop that first segment.
        relative_parts = parts[1:]
        if any(part in SKIPPED_DIRECTORIES for part in relative_parts[:-1]):
            continue
        name = relative_parts[-1]
        if name in SKIPPED_NAMES or name.lower().endswith(tuple(SKIPPED_SUFFIXES)):
            continue
        relative = "/".join(relative_parts)
        if not path_selected(relative, focus, exclude):
            continue
        selected.append((_priority(relative, len(relative_parts)), member, relative))
    selected.sort(key=lambda entry: entry[0])
    return selected


def empty_reason(archive_bytes: bytes, focus: Sequence[str], exclude: Sequence[str]) -> str:
    """Why an archive gave a run no file to read, as a ``repository_problems`` code: it holds no
    file at all, every file is one a run skips (or binary), or the board's globs leave none."""
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            held = any(
                member.isfile() and member.size > 0 and "/" in member.name.strip("/")
                for member in archive.getmembers()
            )
            if not held:
                return EMPTY_ARCHIVE
            if (
                (focus or exclude)
                and select_members(archive)
                and not select_members(archive, focus=focus, exclude=exclude)
            ):
                return PATHS_MATCH_NOTHING
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        return "malformed_archive"
    return NOTHING_READABLE


def manifest_entry_chars(entry: ManifestEntry) -> int:
    """What one manifest entry takes in the context JSON, with the separator before it."""
    return len(json.dumps(entry, ensure_ascii=False)) + 2


def manifest_room(selected: Sequence[Selected], budget_chars: int | None) -> tuple[int, int]:
    """How many of ``selected`` the manifest lists, and the characters it keeps for them.

    At most ``MAX_MANIFEST_ENTRIES``, in priority order; with a budget only as many as fit in it.
    Each entry is counted as not sent, the longer of its two forms, so the files chosen in what is
    left can never push the manifest past its room.
    """
    limit = min(len(selected), MAX_MANIFEST_ENTRIES)
    room = 0
    for index, (_key, member, relative) in enumerate(selected[:limit]):
        cost = manifest_entry_chars({"path": relative, "bytes": member.size, "sent": False})
        if budget_chars is not None and room + cost > budget_chars:
            return index, room
        room += cost
    return limit, room


def manifest_of(
    selected: Sequence[Selected], listed: int, sent: Collection[int]
) -> list[ManifestEntry]:
    """The first ``listed`` files of ``selected``, each marked sent if ``sent`` holds its index."""
    return [
        {"path": relative, "bytes": member.size, "sent": index in sent}
        for index, (_key, member, relative) in enumerate(selected[:listed])
    ]
