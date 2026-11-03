"""A bounded, read-only snapshot of the repositories a board links, for a generation run.

The generation path is a single provider call: there is no tool loop and the model cannot reach the
network. Whatever it may inspect is therefore fetched here, once, with hard caps, and placed in the
prompt as data. Nothing is written back to a repository.

A repository comes as a tarball of one commit, from one of two providers: ``github`` downloads it
through the GitHub API, ``git_https`` fetches the latest main branch into the Tralala-managed
mirror and archives it there (``repo_mirror.py``). Everything after the tarball is shared, so
filters, the board link's focus and exclude globs, caps, order and budget are the same for both
(``repo_snapshot_select.py`` decides which files are considered and in which order).

Three rules shape the code below.

- **The archive is untrusted.** A tarball can expand to gigabytes, carry path traversal, or hide
  instructions addressed at the model. It is read into memory with a byte cap while streaming, the
  members are filtered by an allowlist of what can inform an analysis, and the prompt frames the
  result as material to analyse.
- **Failure is per repository.** A repository that cannot be read must not fail the run: it appears
  in the context as an error entry, so the analysis can say which part of the code it did not see.
- **What was not sent still exists.** A file that does not fit the caps or the budget is skipped
  and the next one is read, and the entry's ``manifest`` lists every file considered, marked sent
  or not, so the model never takes a file it was not given for a file that is missing.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, TypedDict
from urllib.parse import urlsplit

from pydantic import JsonValue

from ..core.errors import ValidationFailure
from ..repositories.code_repositories import MirrorRecord
from .repo_archive_cache import ArchiveCache
from .repo_mirror import MirrorRequest, MirrorSnapshot
from .repo_mirror_git import MirrorError
from .repo_snapshot_select import (
    MAX_MANIFEST_ENTRIES,
    ManifestEntry,
    manifest_entry_chars,
    manifest_of,
    manifest_room,
    path_selected,
    select_members,
)
from .repositories import API_BASE, RepositoryEntry, RepositoryService

if TYPE_CHECKING:  # httpx is imported where a client is built
    import httpx

__all__ = [
    "ARCHIVE_MAX_BYTES",
    "MAX_FILES",
    "MAX_MANIFEST_ENTRIES",
    "MAX_TEXT_BYTES",
    "ManifestEntry",
    "RepositorySnapshotService",
    "Snapshot",
    "SnapshotError",
    "SnapshotFile",
    "fetch_archive",
    "file_chars",
    "manifest_entry_chars",
    "path_selected",
    "read_snapshot",
    "resolve_commit",
    "select_members",
]

logger = logging.getLogger("tralala.repo_snapshot")

ARCHIVE_MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 200
MAX_TEXT_BYTES = 200 * 1024
TIMEOUT_SECONDS = 15.0
CODELOAD_HOSTS = frozenset({"codeload.github.com"})


type JsonObject = dict[str, JsonValue]

# Set by tests to run the whole path against httpx.MockTransport instead of the network.
TRANSPORT: httpx.BaseTransport | None = None


class SnapshotFile(TypedDict):
    """One file of the snapshot: its path below the repository root, its size and its text."""

    path: str
    bytes: int
    content: str


class Snapshot(TypedDict):
    """The bounded file set read from one archive and the manifest of every file considered;
    ``chars`` is what its files and its manifest take in a run's context JSON."""

    files: list[SnapshotFile]
    truncated: bool
    text_bytes: int
    chars: int
    manifest: list[ManifestEntry]
    manifest_omitted: int


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


def _least_chars(relative: str, size: int) -> int:
    """The fewest characters a file of ``size`` bytes can take in the context JSON: UTF-8 spends at
    most four bytes on a character and JSON never shortens one, so a file whose least does not fit
    is skipped without being extracted."""
    return file_chars({"path": relative, "bytes": size, "content": ""}) + -(-size // 4)


def _text(archive: tarfile.TarFile, member: tarfile.TarInfo) -> tuple[str, int] | None:
    """A member's text and its size in bytes; ``None`` for one that cannot be read or is binary."""
    handle = archive.extractfile(member)
    if handle is None:
        return None
    payload = handle.read()
    if not _is_text(payload):
        return None
    try:
        return payload.decode("utf-8"), len(payload)
    except UnicodeDecodeError:
        return payload.decode("utf-8", errors="replace"), len(payload)


def read_snapshot(
    archive_bytes: bytes,
    *,
    budget_chars: int | None = None,
    focus: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> Snapshot:
    """Extract the bounded, ordered file set from one tarball, with the manifest of every file
    considered. ``focus`` and ``exclude`` are the board link's globs (``select_members``).

    The manifest takes its room of ``budget_chars`` first (``manifest_room``), and the files share
    what it leaves. A file that would take the text past ``MAX_TEXT_BYTES`` or the files past that
    room is skipped and reading goes on with the next, so one large file no longer hides every
    file after it; only ``MAX_FILES`` ends the reading. ``truncated`` says that a file was left
    out either way.
    """
    try:
        # Opened apart from the `with` below, so only a failed open is malformed_archive.
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")  # noqa: SIM115 - see above
    except (tarfile.TarError, OSError) as exc:
        raise SnapshotError("malformed_archive") from exc
    files: list[SnapshotFile] = []
    sent: set[int] = set()
    used_bytes = 0
    used_chars = 0
    truncated = False
    with archive:
        selected = select_members(archive, focus=focus, exclude=exclude)
        listed, manifest_chars = manifest_room(selected, budget_chars)
        room = None if budget_chars is None else budget_chars - manifest_chars
        for index, (_key, member, relative) in enumerate(selected):
            if len(files) >= MAX_FILES:
                truncated = True
                break
            least = _least_chars(relative, member.size)
            if used_bytes + member.size > MAX_TEXT_BYTES or (
                room is not None and used_chars + least > room
            ):
                truncated = True
                continue
            text = _text(archive, member)
            if text is None:
                continue
            content, size = text
            file: SnapshotFile = {"path": relative, "bytes": size, "content": content}
            cost = file_chars(file)
            if room is not None and used_chars + cost > room:
                truncated = True
                continue
            files.append(file)
            sent.add(index)
            used_bytes += size
            used_chars += cost
    manifest = manifest_of(selected, listed, sent)
    return {
        "files": files,
        "truncated": truncated,
        "text_bytes": used_bytes,
        "chars": used_chars + sum(manifest_entry_chars(entry) for entry in manifest),
        "manifest": manifest,
        "manifest_omitted": len(selected) - listed,
    }


def _log_captured(repository_id: str, sha: str, snapshot: Snapshot, started: float) -> None:
    logger.info(
        "repository_snapshot_captured",
        extra={
            "repository_id": repository_id,
            "commit_sha": sha,
            "files": len(snapshot["files"]),
            "text_bytes": snapshot["text_bytes"],
            "truncated": snapshot["truncated"],
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )


def _contents(snapshot: Snapshot, budget: int | None) -> JsonObject:
    """The snapshot's part of an entry: the manifest and the files, and with a budget what it
    allowed and what the two used of it."""
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
    omitted = snapshot["manifest_omitted"]
    return {
        "file_count": len(snapshot["files"]),
        "truncated": snapshot["truncated"],
        **budgeted,
        # Every file considered, sent or not: what was not sent still exists.
        "manifest": [
            {"path": entry["path"], "bytes": entry["bytes"], "sent": entry["sent"]}
            for entry in snapshot["manifest"]
        ],
        **({"manifest_omitted": omitted} if omitted else {}),
        "files": [
            {"path": file["path"], "bytes": file["bytes"], "content": file["content"]}
            for file in snapshot["files"]
        ],
    }


def _read_steered(archive: bytes, row: RepositoryEntry, budget: int | None) -> Snapshot:
    """``read_snapshot`` through the globs of the repository's link to the board."""
    return read_snapshot(
        archive,
        budget_chars=budget,
        focus=row.get("focus_paths", []),
        exclude=row.get("exclude_paths", []),
    )


def _named_globs(row: RepositoryEntry) -> JsonObject:
    """The link's globs for the entry, only when it has some: the run should know that the board
    narrowed what it reads."""
    named: JsonObject = {}
    focus = row.get("focus_paths", [])
    exclude = row.get("exclude_paths", [])
    if focus:
        named["focus_paths"] = [*focus]
    if exclude:
        named["exclude_paths"] = [*exclude]
    return named


class RepositorySource(Protocol):
    """What a snapshot needs of ``RepositoryService``: the board's enabled repositories in link
    order, a repository's token, and where a mirror's outcome is recorded."""

    def for_board(self, board_id: str) -> list[RepositoryEntry]: ...

    def token(self, repository_id: str) -> str | None: ...

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None: ...

    def record_mirror_error(self, repository_id: str, code: str) -> None: ...


class MirrorSource(Protocol):
    """``MirrorService.read_latest``: fetch the repository's branch, then archive what it holds."""

    def read_latest(self, request: MirrorRequest, token: str | None) -> MirrorSnapshot: ...


class RepositorySnapshotService:
    """Turn a board's repository links into the snapshot one generation run may see."""

    def __init__(
        self,
        repositories: RepositorySource,
        mirror: MirrorSource | None = None,
        archives: ArchiveCache | None = None,
    ) -> None:
        self.repositories = repositories
        self.mirror = mirror
        # A GitHub commit's archive never changes: a second run on it reads the cached one.
        self.archives = archives

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
            **_named_globs(row),
        }
        if row["provider"] == "git_https":
            return self._from_mirror(row, entry, budget)
        try:
            owner, name = RepositoryService.parse(row["url"])
        except ValidationFailure:
            return {**entry, "error": "invalid_url"}
        token = self.repositories.token(row["id"])
        started = time.monotonic()
        try:
            sha = resolve_commit(owner, name, row.get("branch"), token)
            archive = self._archive(row["id"], owner, name, sha, token)
            snapshot = _read_steered(archive, row, budget)
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
        _log_captured(row["id"], sha, snapshot, started)
        return {**entry, "commit_sha": sha, **_contents(snapshot, budget)}

    def _archive(
        self, repository_id: str, owner: str, name: str, sha: str, token: str | None
    ) -> bytes:
        cached = None if self.archives is None else self.archives.get(repository_id, sha)
        if cached is not None:
            return cached
        archive = fetch_archive(owner, name, sha, token)
        if self.archives is not None:
            self.archives.put(repository_id, sha, archive)
        return archive

    def _from_mirror(
        self, row: RepositoryEntry, entry: JsonObject, budget: int | None
    ) -> JsonObject:
        """The repository's latest main branch through the mirror, with what the run should know
        of it: the branch, the commit, when it was fetched and whether that fetch failed."""
        entry = {**entry, "provider": "git_https"}
        started = time.monotonic()
        request = MirrorRequest(repository_id=row["id"], url=row["url"], branch=row["branch"])
        try:
            latest = self._read_latest(request)
            snapshot = _read_steered(latest.archive, row, budget)
        except (MirrorError, SnapshotError) as exc:
            self.repositories.record_mirror_error(row["id"], exc.code)
            logger.warning(
                "repository_snapshot_failed",
                extra={
                    "repository_id": row["id"],
                    "provider": "git_https",
                    "code": exc.code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return {**entry, "error": exc.code}
        head = latest.head
        if head.fetch_error is not None:
            self.repositories.record_mirror_error(row["id"], head.fetch_error)
        else:
            record = MirrorRecord(
                default_branch=head.default_branch,
                last_sha=latest.commit_sha,
                fetched_at=head.fetched_at,
                mirror_bytes=head.mirror_bytes,
            )
            self.repositories.record_fetch(row["id"], record)
        _log_captured(row["id"], latest.commit_sha, snapshot, started)
        return {
            **entry,
            "branch": head.branch,
            "commit_sha": latest.commit_sha,
            "fetched_at": head.fetched_at,
            "stale_mirror": head.stale_mirror,
            **({"fetch_error": head.fetch_error} if head.fetch_error else {}),
            **_contents(snapshot, budget),
        }

    def _read_latest(self, request: MirrorRequest) -> MirrorSnapshot:
        if self.mirror is None:
            raise MirrorError("git_missing")
        return self.mirror.read_latest(request, self.repositories.token(request.repository_id))

    @staticmethod
    def describe() -> str:
        """The caps as a sentence, so the prompt states what it was given and what it was not."""
        return (
            f"At most {ARCHIVE_MAX_BYTES // (1024 * 1024)} MB of archive, {MAX_FILES} files and "
            f"{MAX_TEXT_BYTES // 1024} KB of text are sent, less when the documents leave less "
            "room; build output, dependencies, lock files, binaries and images are skipped."
        )
