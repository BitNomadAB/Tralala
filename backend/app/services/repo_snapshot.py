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
import logging
import tarfile
from typing import Any
from urllib.parse import urlsplit

from ..core.errors import ValidationFailure
from .repositories import API_BASE, RepositoryService

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

# Set by tests to run the whole path against httpx.MockTransport instead of the network.
TRANSPORT: Any | None = None


def _client() -> Any:
    import httpx

    kwargs: dict[str, Any] = {"timeout": TIMEOUT_SECONDS, "follow_redirects": False}
    if TRANSPORT is not None:
        kwargs["transport"] = TRANSPORT
    return httpx.Client(**kwargs)


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tralala",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _classify(status: int, headers: Any | None = None) -> str:
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


def resolve_commit(owner: str, name: str, branch: str | None, token: str | None) -> str:
    """Return the commit SHA at the branch head, so two runs can be compared exactly."""
    ref = branch or "HEAD"
    try:
        with _client() as client:
            response = client.get(
                f"{API_BASE}/repos/{owner}/{name}/commits/{ref}", headers=_headers(token)
            )
    except Exception as exc:  # noqa: BLE001 - reported, never raised past this module
        code = "timeout" if "timeout" in type(exc).__name__.lower() else "unreachable"
        raise SnapshotError(code) from exc
    if response.status_code >= 400:
        raise SnapshotError(_classify(response.status_code, response.headers))
    try:
        payload = response.json()
    except ValueError as exc:
        raise SnapshotError("malformed_response") from exc
    sha = str((payload or {}).get("sha") or "")
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
    except SnapshotError:
        raise
    except Exception as exc:  # noqa: BLE001
        code = "timeout" if "timeout" in type(exc).__name__.lower() else "unreachable"
        raise SnapshotError(code) from exc


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


def read_snapshot(archive_bytes: bytes) -> dict[str, Any]:
    """Extract the bounded, ordered file set from one tarball."""
    files: list[dict[str, Any]] = []
    used_bytes = 0
    truncated = False
    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")
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
            files.append({"path": relative, "bytes": len(payload), "content": content})
            used_bytes += len(payload)
    return {"files": files, "truncated": truncated, "text_bytes": used_bytes}


class RepositorySnapshotService:
    """Turn a board's repository links into the snapshot one generation run may see."""

    def __init__(self, repositories: RepositoryService) -> None:
        self.repositories = repositories

    def for_board(self, board_id: str) -> list[dict[str, Any]]:
        """One entry per enabled repository on the board; failures are entries, not exceptions."""
        entries: list[dict[str, Any]] = []
        for row in self.repositories.for_board(board_id):
            entries.append(self._one(row))
        return entries

    def _one(self, row: dict[str, Any]) -> dict[str, Any]:
        entry: dict[str, Any] = {
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
        try:
            sha = resolve_commit(owner, name, row.get("branch"), token)
            archive = fetch_archive(owner, name, sha, token)
            snapshot = read_snapshot(archive)
        except SnapshotError as exc:
            logger.warning(
                '{"event": "repository_snapshot_failed", "repository_id": "%s", "code": "%s"}',
                row["id"],
                exc.code,
            )
            return {**entry, "error": exc.code}
        logger.info(
            '{"event": "repository_snapshot_captured", "repository_id": "%s", "commit_sha": "%s",'
            ' "files": %d, "text_bytes": %d, "truncated": %s}',
            row["id"],
            sha,
            len(snapshot["files"]),
            snapshot["text_bytes"],
            "true" if snapshot["truncated"] else "false",
        )
        return {
            **entry,
            "commit_sha": sha,
            "file_count": len(snapshot["files"]),
            "truncated": snapshot["truncated"],
            "files": snapshot["files"],
        }

    @staticmethod
    def describe() -> str:
        """The caps as a sentence, so the prompt states what it was given and what it was not."""
        return (
            f"At most {ARCHIVE_MAX_BYTES // (1024 * 1024)} MB of archive, {MAX_FILES} files and "
            f"{MAX_TEXT_BYTES // 1024} KB of text are sent; build output, dependencies, lock "
            "files, binaries and images are skipped."
        )
