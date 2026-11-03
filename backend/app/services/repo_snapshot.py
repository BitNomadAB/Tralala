"""A bounded, read-only snapshot of the repositories a board links, for a generation run.

The generation path is a single provider call: there is no tool loop and the model cannot reach the
network. Whatever it may inspect is therefore fetched here, once, with hard caps, and placed in the
prompt as data. Nothing is cloned into the data directory, no `git` binary runs, and nothing is
written back to the repository.

Two rules shape the code below.

- **The archive is untrusted.** A tarball can expand to gigabytes, carry path traversal, or hide
  instructions addressed at the model. It is read into memory with a byte cap while streaming, the
  members are filtered by an allowlist of what can inform an analysis, and the prompt frames the
  result as material to analyse.
- **Failure is per repository.** A repository that cannot be read must not fail the run: it appears
  in the context as an error entry, so the analysis can say which part of the code it did not see.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile
import time
from typing import TYPE_CHECKING, Protocol, TypedDict
from urllib.parse import urlsplit

from pydantic import JsonValue

from ..core.errors import ValidationFailure
from .repositories import API_BASE, RepositoryEntry, RepositoryService

if TYPE_CHECKING:  # httpx is imported where a client is built
    import httpx

logger = logging.getLogger("tralala.repo_snapshot")

ARCHIVE_MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 200
MAX_TEXT_BYTES = 200 * 1024
TIMEOUT_SECONDS = 15.0
CODELOAD_HOSTS = frozenset({"codeload.github.com"})

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

type JsonObject = dict[str, JsonValue]

# Set by tests to run the whole path against httpx.MockTransport instead of the network.
TRANSPORT: httpx.BaseTransport | None = None


class SnapshotFile(TypedDict):
    """One file of the snapshot: its path below the repository root, its size and its text."""

    path: str
    bytes: int
    content: str


class Snapshot(TypedDict):
    """The bounded file set read from one archive; ``chars`` is what its files take in a run's
    context JSON."""

    files: list[SnapshotFile]
    truncated: bool
    text_bytes: int
    chars: int


def file_chars(file: SnapshotFile) -> int:
    """What one file takes in the context JSON, with the separator before it."""
    return len(json.dumps(file, ensure_ascii=False)) + 2


def _client() -> httpx.Client:
    import httpx

    # No transport is httpx's own default, exactly as if none were passed.
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=TRANSPORT)


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tralala",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _classify(status: int, headers: httpx.Headers | None = None) -> str:
    """Name the failure the way an operator reads it, never with GitHub's body."""
    if status == 401:
        return "unauthorized"
    if status == 404:
        return "not_found"
    if status in (403, 429):
        remaining = ""
        if headers is not None:
            remaining = str(headers.get("x-ratelimit-remaining") or "")
        return "rate_limited" if status == 429 or remaining == "0" else "forbidden"
    return "unreachable"


def _json_object(value: JsonValue) -> JsonObject:
    """``value`` as a JSON object. Anything else raises the ``AttributeError`` that reading a key
    from it (``.get``) always raised, so a malformed answer fails exactly as before."""
    if isinstance(value, dict):
        return value
    raise AttributeError(f"'{type(value).__name__}' object has no attribute 'get'")


def resolve_commit(owner: str, name: str, branch: str | None, token: str | None) -> str:
    """Return the commit SHA at the branch head, so two runs can be compared exactly."""
    ref = branch or "HEAD"
    try:
        with _client() as client:
            response = client.get(
                f"{API_BASE}/repos/{owner}/{name}/commits/{ref}", headers=_headers(token)
            )
    except Exception as exc:  # reported, never raised past this module
        code = "timeout" if "timeout" in type(exc).__name__.lower() else "unreachable"
        raise SnapshotError(code) from exc
    if response.status_code >= 400:
        raise SnapshotError(_classify(response.status_code, response.headers))
    payload: JsonValue
    try:
        payload = response.json()
    except ValueError as exc:
        raise SnapshotError("malformed_response") from exc
    sha = str(_json_object(payload or {}).get("sha") or "")
    if not sha:
        raise SnapshotError("malformed_response")
    return sha


class SnapshotError(Exception):
    """A repository that cannot be read. The code is what reaches the prompt and the log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def fetch_archive(owner: str, name: str, sha: str, token: str | None) -> bytes:
    """Download the tarball for one commit, following exactly one hop to codeload.

    GitHub answers 302 to `codeload.github.com`. Following redirects automatically would send the
    token to whatever host the response named, so the hop is checked here and the archive request
    carries no credential at all.
    """
    url = f"{API_BASE}/repos/{owner}/{name}/tarball/{sha}"
    try:
        with _client() as client:
            return _download(client, url, token)
    except SnapshotError:
        raise
    except Exception as exc:  # reported, never raised past this module
        code = "timeout" if "timeout" in type(exc).__name__.lower() else "unreachable"
        raise SnapshotError(code) from exc


def _download(client: httpx.Client, url: str, token: str | None) -> bytes:
    """The archive request itself; every refusal is a SnapshotError with its code."""
    response = client.get(url, headers=_headers(token))
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get("location") or ""
        host = (urlsplit(location).hostname or "").lower()
        if host not in CODELOAD_HOSTS:
            raise SnapshotError("redirect_refused")
        buffer = bytearray()
        with client.stream("GET", location, headers={"User-Agent": "tralala"}) as stream:
            if stream.status_code >= 400:
                raise SnapshotError(_classify(stream.status_code, stream.headers))
            for chunk in stream.iter_bytes():
                buffer.extend(chunk)
                if len(buffer) > ARCHIVE_MAX_BYTES:
                    raise SnapshotError("too_large")
        return bytes(buffer)
    if response.status_code >= 400:
        raise SnapshotError(_classify(response.status_code, response.headers))
    if len(response.content) > ARCHIVE_MAX_BYTES:
        raise SnapshotError("too_large")
    return response.content


def _is_text(payload: bytes) -> bool:
    return b"\x00" not in payload


def _priority(relative: str, depth: int) -> tuple[int, int, str]:
    name = relative.rsplit("/", 1)[-1]
    if depth == 1 and (name.upper().startswith("README") or name == "AGENTS.md"):
        return (ROOT_DOC_PRIORITY, 0, relative)
    if relative.startswith("docs/"):
        return (DOCS_PRIORITY, depth, relative)
    if depth == 1 and (name in CONFIG_NAMES or name.endswith((".toml", ".json", ".yml", ".yaml"))):
        return (CONFIG_PRIORITY, depth, relative)
    return (SOURCE_PRIORITY, depth, relative)


def select_members(
    archive: tarfile.TarFile,
) -> list[tuple[tuple[int, int, str], tarfile.TarInfo, str]]:
    """Everything worth reading, ordered so the same SHA always yields the same prompt."""
    selected: list[tuple[tuple[int, int, str], tarfile.TarInfo, str]] = []
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
        selected.append((_priority(relative, len(relative_parts)), member, relative))
    selected.sort(key=lambda entry: entry[0])
    return selected


def read_snapshot(archive_bytes: bytes, *, budget_chars: int | None = None) -> Snapshot:
    """Extract the bounded, ordered file set from one tarball; with ``budget_chars``, the files
    also stop where the next one would not fit in that many characters of context."""
    files: list[SnapshotFile] = []
    used_bytes = 0
    used_chars = 0
    truncated = False
    try:
        # Opened apart from the `with` below, so only a failed open is malformed_archive.
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")  # noqa: SIM115 - see above
    except (tarfile.TarError, OSError) as exc:
        raise SnapshotError("malformed_archive") from exc
    with archive:
        for _priority_key, member, relative in select_members(archive):
            if len(files) >= MAX_FILES:
                truncated = True
                break
            if used_bytes + member.size > MAX_TEXT_BYTES:
                truncated = True
                break
            handle = archive.extractfile(member)
            if handle is None:
                continue
            payload = handle.read()
            if not _is_text(payload):
                continue
            try:
                content = payload.decode("utf-8")
            except UnicodeDecodeError:
                content = payload.decode("utf-8", errors="replace")
            file: SnapshotFile = {"path": relative, "bytes": len(payload), "content": content}
            cost = file_chars(file)
            if budget_chars is not None and used_chars + cost > budget_chars:
                truncated = True
                break
            files.append(file)
            used_bytes += len(payload)
            used_chars += cost
    return {"files": files, "truncated": truncated, "text_bytes": used_bytes, "chars": used_chars}


class RepositorySource(Protocol):
    """What a snapshot needs of ``RepositoryService``: the board's enabled repositories in link
    order, and a repository's token."""

    def for_board(self, board_id: str) -> list[RepositoryEntry]: ...

    def token(self, repository_id: str) -> str | None: ...


class RepositorySnapshotService:
    """Turn a board's repository links into the snapshot one generation run may see."""

    def __init__(self, repositories: RepositorySource) -> None:
        self.repositories = repositories

    def for_board(self, board_id: str, *, budget_chars: int | None = None) -> list[JsonObject]:
        """One entry per enabled repository on the board; failures are entries, not exceptions.

        With ``budget_chars`` the repositories share it in link order: each gets an even share of
        what is left, so what one does not use (a small repository, a failed fetch) carries over to
        the next.
        """
        rows = self.repositories.for_board(board_id)
        if not rows:
            # Silent here used to look like a successful fetch in the run panel: say so in the log.
            logger.info("repository_snapshot_none", extra={"board_id": board_id})
            return []
        if budget_chars is None:
            return [self._one(row, None) for row in rows]
        entries: list[JsonObject] = []
        remaining = budget_chars
        for index, row in enumerate(rows):
            entry = self._one(row, remaining // (len(rows) - index))
            included = entry.get("snapshot_chars_included")
            remaining -= included if isinstance(included, int) else 0
            entries.append(entry)
        return entries

    def _one(self, row: RepositoryEntry, budget: int | None) -> JsonObject:
        entry: JsonObject = {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "branch": row.get("branch"),
        }
        try:
            owner, name = RepositoryService.parse(row["url"])
        except ValidationFailure:
            return {**entry, "error": "invalid_url"}
        token = self.repositories.token(row["id"])
        started = time.monotonic()
        try:
            sha = resolve_commit(owner, name, row.get("branch"), token)
            archive = fetch_archive(owner, name, sha, token)
            snapshot = read_snapshot(archive, budget_chars=budget)
        except SnapshotError as exc:
            logger.warning(
                "repository_snapshot_failed",
                extra={
                    "repository_id": row["id"],
                    "code": exc.code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return {**entry, "error": exc.code}
        logger.info(
            "repository_snapshot_captured",
            extra={
                "repository_id": row["id"],
                "commit_sha": sha,
                "files": len(snapshot["files"]),
                "text_bytes": snapshot["text_bytes"],
                "truncated": snapshot["truncated"],
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        budgeted: JsonObject = (
            {}
            if budget is None
            else {
                "budget_chars": budget,
                "snapshot_chars_included": snapshot["chars"],
                # Not even the first file fitted in this repository's share.
                "content_omitted": not snapshot["files"] and snapshot["truncated"],
            }
        )
        return {
            **entry,
            "commit_sha": sha,
            "file_count": len(snapshot["files"]),
            "truncated": snapshot["truncated"],
            **budgeted,
            "files": [
                {"path": file["path"], "bytes": file["bytes"], "content": file["content"]}
                for file in snapshot["files"]
            ],
        }

    @staticmethod
    def describe() -> str:
        """The caps as a sentence, so the prompt states what it was given and what it was not."""
        return (
            f"At most {ARCHIVE_MAX_BYTES // (1024 * 1024)} MB of archive, {MAX_FILES} files and "
            f"{MAX_TEXT_BYTES // 1024} KB of text are sent, less when the documents leave less "
            "room; build output, dependencies, lock files, binaries and images are skipped."
        )
