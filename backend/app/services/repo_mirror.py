"""The Tralala-managed mirror: the latest main branch of a repository on any allowed HTTPS host.

A repository with the provider ``git_https`` is read from one shallow, single-branch bare mirror
under ``<data>/repos/<repository_id>/mirror.git`` (``repo_mirror_files.py``):

- **Main branch.** Without an explicit branch on the repository, ``git ls-remote --symref`` names
  the branch the remote's HEAD points at (``main``, ``master`` or whatever it is); an explicit
  branch wins.
- **Before every run** the first read clones (``--bare --depth 1 --single-branch``), every later one
  fetches that branch (``--depth 1 --prune``) and then runs the hygiene, ``reflog expire
  --expire=now --all`` and ``gc --prune=now``, so the mirror stays about one commit in size. A
  mirror still larger than ``TRALALA_REPOSITORY_MIRROR_MAX_BYTES`` after that is removed and the run
  is told ``too_large``; the next run clones it again.
- **A failed fetch** falls back to the last good mirror: the run reads the commit it already had and
  says so (``stale_mirror`` with the old ``fetched_at``). Without a good mirror the failure is the
  repository's error entry, and the run goes on without it.
- **The snapshot** is ``git archive`` of the branch, the same tar shape the GitHub path downloads,
  so ``repo_snapshot.read_snapshot`` applies the same filters, caps, order and budget. The commit is
  read from the archive itself (git stores it as the tar's global ``comment`` header), so the files
  and the commit they are recorded under can never disagree, and no git-internal file is parsed.
- **One operation at a time per repository**: a lock per repository id serialises fetch, archive
  and removal. ``TRALALA_REPOSITORY_FETCH_TIMEOUT_SECONDS`` bounds each git command.

The service never touches storage itself: the repository row is the caller's (the registry unit of
work behind ``RepositoryService``), the files come through ``MirrorFiles`` and the one subprocess
through ``RunGit``, so a unit test drives every rule here with fakes of both.
"""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Final

from ..core.dates import utcnow
from .repo_mirror_files import MirrorFiles, MirrorState
from .repo_mirror_git import (
    SHA_PATTERN,
    MirrorError,
    RunGit,
    git_args,
    git_environment,
    git_url_problem,
    parse_ls_remote,
    valid_branch,
)

logger = logging.getLogger("tralala.repo_mirror")

# ``git archive`` writes the whole tree of one commit; the snapshot reads at most 200 KB of it, so a
# tree larger than this is refused rather than held in memory.
ARCHIVE_MAX_BYTES: Final = 128 * 1024 * 1024
# read_snapshot drops the first path segment, which on GitHub is ``<owner>-<repo>-<sha>/``.
ARCHIVE_PREFIX: Final = "snapshot/"
# Failures after which the last good mirror is still the repository the run should read.
FALLBACK_CODES: Final = frozenset({"auth_failed", "not_found", "timeout", "fetch_failed"})


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorRequest:
    """Which repository to read: its id, its URL and the branch it names (None: the remote's
    default branch)."""

    repository_id: str
    url: str
    branch: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteHead:
    """What ``ls-remote`` said: the default branch, and whether an explicit branch exists."""

    default_branch: str
    branch_found: bool | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorHead:
    """The mirror after a fetch: the branch it holds and when it was last brought up to date.

    ``stale_mirror`` says the fetch failed and the mirror is the last good one; ``fetch_error`` is
    why.
    """

    branch: str
    default_branch: str | None
    fetched_at: str
    mirror_bytes: int
    stale_mirror: bool
    fetch_error: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorArchive:
    """One commit's files as a gzip tarball, and the commit, read from the archive itself."""

    commit_sha: str
    data: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorSnapshot:
    """A fetch and the archive of what it brought, taken under one hold of the repository's lock."""

    head: MirrorHead
    commit_sha: str
    archive: bytes


def archive_commit(tar: bytes) -> str | None:
    """The commit ``git archive`` recorded in the tar's global pax header, or None."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
            comment = archive.pax_headers.get("comment", "")
    except (tarfile.TarError, OSError):
        return None
    return comment if SHA_PATTERN.fullmatch(comment) else None


class MirrorService:
    def __init__(
        self,
        run_git: RunGit,
        files: MirrorFiles,
        *,
        hosts: frozenset[str],
        max_bytes: int,
        timeout_seconds: float,
        archive_max_bytes: int = ARCHIVE_MAX_BYTES,
        clock: Callable[[], str] = utcnow,
    ) -> None:
        self._run_git = run_git
        self._files = files
        self._hosts = hosts
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds
        self._archive_max_bytes = archive_max_bytes
        self._clock = clock
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, repository_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(repository_id, threading.Lock())

    def _git(
        self, args: list[str], *, token: str | None = None, max_output_bytes: int | None = None
    ) -> bytes:
        return self._run_git(
            args,
            env=git_environment(token),
            timeout=self._timeout,
            max_output_bytes=max_output_bytes,
        )

    def _require_url(self, url: str) -> None:
        problem = git_url_problem(url, self._hosts)
        if problem is not None:
            raise MirrorError(problem)

    # --- the remote -------------------------------------------------------------------------------

    def ls_remote_default_branch(
        self, url: str, token: str | None, *, branch: str | None = None
    ) -> RemoteHead:
        """The branch the remote's HEAD names, without cloning; with ``branch``, also whether that
        branch exists."""
        self._require_url(url)
        if branch is not None and not valid_branch(branch):
            raise MirrorError("not_found")
        patterns = ["HEAD"] if branch is None else ["HEAD", f"refs/heads/{branch}"]
        output = self._git(git_args("ls-remote", "--symref", "--", url, *patterns), token=token)
        refs = parse_ls_remote(output.decode("utf-8", errors="replace"))
        if refs.head is None or not valid_branch(refs.head):
            raise MirrorError("fetch_failed")
        found = None if branch is None else branch in refs.branches
        return RemoteHead(default_branch=refs.head, branch_found=found)

    # --- fetch ------------------------------------------------------------------------------------

    def fetch_latest(self, request: MirrorRequest, token: str | None) -> MirrorHead:
        """Bring the mirror to the branch's latest commit: clone on the first read, fetch and
        clean up after that, the last good mirror when the fetch fails."""
        with self._lock(request.repository_id):
            return self._fetch_latest(request, token)

    def read_latest(self, request: MirrorRequest, token: str | None) -> MirrorSnapshot:
        """``fetch_latest`` and the archive of the branch, so no other fetch comes between."""
        with self._lock(request.repository_id):
            head = self._fetch_latest(request, token)
            archive = self._archive(request.repository_id, head.branch)
            self._remember_commit(request.repository_id, archive.commit_sha)
        return MirrorSnapshot(head=head, commit_sha=archive.commit_sha, archive=archive.data)

    def _last_good(self, request: MirrorRequest) -> MirrorState | None:
        state = self._files.read_state(request.repository_id)
        if state is None or state["url"] != request.url or not state["fetched_at"]:
            return None
        return state if self._files.has_mirror(request.repository_id) else None

    def _fetch_latest(self, request: MirrorRequest, token: str | None) -> MirrorHead:
        self._require_url(request.url)
        if request.branch is not None and not valid_branch(request.branch):
            raise MirrorError("not_found")
        repository_id = request.repository_id
        good = self._last_good(request)
        started = time.monotonic()
        branch = request.branch
        default_branch = None if good is None else good["default_branch"]
        last_sha: str | None = None
        try:
            if branch is None:
                remote = self.ls_remote_default_branch(request.url, token)
                branch = default_branch = remote.default_branch
            if good is not None and good["branch"] == branch:
                self._fetch(repository_id, request.url, branch, token)
                action, last_sha = "repository_mirror_fetched", good["last_sha"]
            else:
                self._clone(repository_id, request.url, branch, token)
                action = "repository_mirror_cloned"
        except MirrorError as exc:
            return self._fall_back(request, good, branch, exc)
        size = self._files.size(repository_id)
        if size > self._max_bytes:
            logger.warning(
                "repository_mirror_too_large",
                extra={
                    "repository_id": repository_id,
                    "mirror_bytes": size,
                    "max_bytes": self._max_bytes,
                },
            )
            self._discard(repository_id)
            raise MirrorError("too_large")
        now = self._clock()
        self._files.write_state(
            repository_id,
            {
                "url": request.url,
                "branch": branch,
                "default_branch": default_branch,
                # The archive that follows records the commit the fetch brought.
                "last_sha": last_sha,
                "fetched_at": now,
                "mirror_bytes": size,
                "last_error": None,
            },
        )
        logger.info(
            action,
            extra={
                "repository_id": repository_id,
                "branch": branch,
                "mirror_bytes": size,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return MirrorHead(
            branch=branch,
            default_branch=default_branch,
            fetched_at=now,
            mirror_bytes=size,
            stale_mirror=False,
            fetch_error=None,
        )

    def _clone(self, repository_id: str, url: str, branch: str, token: str | None) -> None:
        """A new mirror: whatever was there before (another URL or branch, a broken clone) goes."""
        self._discard(repository_id)
        self._files.prepare(repository_id)
        args = git_args(
            "clone",
            "--bare",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            "--no-tags",
            "--",
            url,
            self._files.mirror_path(repository_id),
        )
        try:
            self._git(args, token=token)
        except MirrorError:
            # A clone that stopped halfway is not a mirror to fall back on.
            self._discard(repository_id, quietly=True)
            raise

    def _fetch(self, repository_id: str, url: str, branch: str, token: str | None) -> None:
        """The branch's latest commit into the mirror, then the hygiene. The URL is given on the
        command line every time, so the mirror's own configuration is never what decides where git
        connects."""
        refspec = f"+refs/heads/{branch}:refs/heads/{branch}"
        args = git_args(
            "fetch",
            "--depth",
            "1",
            "--prune",
            "--no-tags",
            "--update-head-ok",
            "--no-auto-gc",
            "--",
            url,
            refspec,
            git_dir=self._files.mirror_path(repository_id),
        )
        self._git(args, token=token)
        self._hygiene(repository_id)

    def _hygiene(self, repository_id: str) -> None:
        """Drop what the previous commit left: its reflog entries, then every unreachable object.
        A failure is logged and the size check after it still bounds the mirror."""
        mirror = self._files.mirror_path(repository_id)
        try:
            self._git(git_args("reflog", "expire", "--expire=now", "--all", git_dir=mirror))
            self._git(git_args("gc", "--prune=now", "--quiet", git_dir=mirror))
        except MirrorError as exc:
            logger.warning(
                "repository_mirror_hygiene_failed",
                extra={"repository_id": repository_id, "code": exc.code},
            )

    def _fall_back(
        self, request: MirrorRequest, good: MirrorState | None, branch: str | None, exc: MirrorError
    ) -> MirrorHead:
        """The last good mirror when the failure leaves it the right one to read; else raise."""
        repository_id = request.repository_id
        fetched_at = None if good is None else good["fetched_at"]
        if (
            good is None
            or fetched_at is None
            or exc.code not in FALLBACK_CODES
            # A new branch or URL was being cloned: the old mirror is not what the run asked for.
            or branch not in (None, good["branch"])
            or not self._files.has_mirror(repository_id)
        ):
            logger.warning(
                "repository_mirror_failed",
                extra={"repository_id": repository_id, "code": exc.code},
            )
            raise exc
        stale = good.copy()
        stale["last_error"] = exc.code
        self._files.write_state(repository_id, stale)
        logger.warning(
            "repository_mirror_stale",
            extra={"repository_id": repository_id, "code": exc.code, "fetched_at": fetched_at},
        )
        return MirrorHead(
            branch=good["branch"],
            default_branch=good["default_branch"],
            fetched_at=fetched_at,
            mirror_bytes=good["mirror_bytes"] or 0,
            stale_mirror=True,
            fetch_error=exc.code,
        )

    # --- archive ----------------------------------------------------------------------------------

    def archive(self, repository_id: str, branch: str) -> MirrorArchive:
        """The branch's files as a gzip tarball, in the shape ``read_snapshot`` reads."""
        with self._lock(repository_id):
            return self._archive(repository_id, branch)

    def _archive(self, repository_id: str, branch: str) -> MirrorArchive:
        if not valid_branch(branch) or not self._files.has_mirror(repository_id):
            raise MirrorError("not_found")
        args = git_args(
            "archive",
            "--format=tar",
            "--prefix=" + ARCHIVE_PREFIX,
            f"refs/heads/{branch}",
            git_dir=self._files.mirror_path(repository_id),
        )
        tar = self._git(args, max_output_bytes=self._archive_max_bytes)
        commit = archive_commit(tar)
        if commit is None:
            raise MirrorError("fetch_failed")
        # Compressed here rather than by git, so no filter command is ever involved.
        return MirrorArchive(commit_sha=commit, data=gzip.compress(tar, compresslevel=1, mtime=0))

    def _remember_commit(self, repository_id: str, commit_sha: str) -> None:
        state = self._files.read_state(repository_id)
        if state is not None and state["last_sha"] != commit_sha:
            state["last_sha"] = commit_sha
            self._files.write_state(repository_id, state)

    # --- removal ----------------------------------------------------------------------------------

    def _discard(self, repository_id: str, *, quietly: bool = False) -> None:
        try:
            self._files.remove(repository_id)
        except OSError as exc:
            logger.warning(
                "repository_mirror_cleanup_failed",
                extra={"repository_id": repository_id, "error": type(exc).__name__},
            )
            if not quietly:
                raise MirrorError("mirror_cleanup_failed") from exc

    def remove(self, repository_id: str) -> None:
        """Remove the repository's mirror and state; ``mirror_cleanup_failed`` when the host still
        holds a file in it after the platform's retries."""
        with self._lock(repository_id):
            self._discard(repository_id)
        logger.info("repository_mirror_removed", extra={"repository_id": repository_id})

    def sweep_orphans(self, known_ids: Collection[str]) -> list[str]:
        """Remove every mirror whose repository is gone; what could not be removed stays logged."""
        removed: list[str] = []
        for repository_id in self._files.repository_ids():
            if repository_id in known_ids:
                continue
            try:
                self.remove(repository_id)
            except MirrorError:
                continue
            removed.append(repository_id)
        return removed
