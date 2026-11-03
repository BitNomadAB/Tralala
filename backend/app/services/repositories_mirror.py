"""The ``git_https`` side of ``RepositoryService``: the check that asks the remote, and the life of
the mirror a run fetches into.

A repository with the provider ``git_https`` is read from a mirror under
``<data>/repos/<repository_id>/`` (``repo_mirror.py``). The mirror is a cache of the repository, so
it goes when nothing will read it again:

- **Deleting the repository** removes the mirror first, in the same operation. When the host still
  holds a file in it after the platform's retries, nothing else changes: the row stays with
  ``mirror_error = mirror_cleanup_failed`` and the delete answers ``409 mirror_cleanup_failed``, so
  the failure is shown on the row, where "Remove now" (``POST /repositories/{id}/mirror/remove``)
  tries again. Once that succeeded, the repository can be deleted.
- **Losing its last board link** removes it too: no run reads it until a board links the repository
  again, and that run clones it. A removal that fails there does not fail the board edit; the row
  shows ``mirror_cleanup_failed`` the same way.
- **"Rebuild mirror"** (``POST /repositories/{id}/mirror/rebuild``) is a removal: the next run
  clones the repository again.
- **At startup** every directory under ``repos/`` without a repository row is removed.

A removal that worked clears what the row said about the mirror (commit, ``fetched_at``, size,
error); the default branch stays, because it describes the remote, not the mirror.

The check of a ``git_https`` repository is ``git ls-remote`` only: it names the remote's default
branch without cloning anything and stores it on the row. ``CheckOutcome`` is the answer of both
providers' checks; the GitHub one lives in ``services.repositories``.

Everything here reaches the registry through the unit of work and the mirror through
``MirrorControl``, which ``MirrorService`` fits, so a unit test drives it with fakes of both.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from typing import Final, Protocol, TypedDict

from pydantic import JsonValue

from ..core.errors import Conflict
from ..db.generated.registry import RepositoriesRow
from ..repositories.registry import RegistryUnitOfWork
from .repo_mirror import RemoteHead
from .repo_mirror_git import ERROR_TEXT, MirrorError

logger = logging.getLogger("tralala.repositories")

CLEANUP_FAILED: Final = "mirror_cleanup_failed"
MIRRORED: Final = "git_https"


class CheckOutcome(TypedDict):
    """What the host said about the repository, without the token or the host's own text."""

    status: str
    detail: str
    default_branch: JsonValue
    private: bool | None
    size_kb: int | None
    checked_at: str


class MirrorControl(Protocol):
    """What ``RepositoryService`` needs of ``MirrorService``: ask the remote without cloning, remove
    one repository's mirror, and remove every mirror whose repository is gone."""

    def ls_remote_default_branch(
        self, url: str, token: str | None, *, branch: str | None = None
    ) -> RemoteHead: ...

    def remove(self, repository_id: str) -> None: ...

    def sweep_orphans(self, known_ids: Collection[str]) -> list[str]: ...


def outcome(status: str, detail: str, now: str) -> CheckOutcome:
    """A check that found nothing more than its status and a sentence about it."""
    return {
        "status": status,
        "detail": detail,
        "default_branch": None,
        "private": None,
        "size_kb": None,
        "checked_at": now,
    }


def store_check(store: RegistryUnitOfWork, repository_id: str, result: CheckOutcome) -> None:
    """The outcome on the row, for the list to show; ``updated_at`` becomes the check's time."""
    with store.writer() as repos:
        repos.code_repositories.record_check(
            repository_id,
            status=result["status"],
            detail=result["detail"],
            now=result["checked_at"],
        )


# --- the check ------------------------------------------------------------------------------------


def _remote_head(
    mirror: MirrorControl | None, row: RepositoriesRow, token: str | None
) -> RemoteHead:
    if mirror is None:
        raise MirrorError("git_missing")
    return mirror.ls_remote_default_branch(row.url, token, branch=row.branch)


def check_remote(
    store: RegistryUnitOfWork,
    mirror: MirrorControl | None,
    row: RepositoriesRow,
    token: str | None,
    now: str,
) -> CheckOutcome:
    """``git ls-remote`` only: the remote's default branch and, when the repository names one,
    whether that branch exists. Nothing is cloned; the default branch is stored on the row."""
    result: CheckOutcome
    try:
        head = _remote_head(mirror, row, token)
    except MirrorError as exc:
        result = outcome(exc.code, ERROR_TEXT.get(exc.code, exc.code), now)
    else:
        with store.writer() as repos:
            repos.code_repositories.record_default_branch(row.id, head.default_branch)
        if head.branch_found is False:
            result = outcome("branch_missing", f"Branch '{row.branch}' does not exist", now)
            result["default_branch"] = head.default_branch
        else:
            result = {
                "status": "ok",
                "detail": f"Readable; the main branch is '{head.default_branch}'",
                "default_branch": head.default_branch,
                "private": None,
                "size_kb": None,
                "checked_at": now,
            }
    store_check(store, row.id, result)
    return result


# --- the mirror's life ----------------------------------------------------------------------------


def remove_mirror(
    store: RegistryUnitOfWork, mirror: MirrorControl | None, repository_id: str
) -> None:
    """Remove the repository's mirror and clear what the row says about it.

    When the host still holds a file in it, the row records ``mirror_cleanup_failed`` and this
    raises ``409 mirror_cleanup_failed``. Without a mirror service (no git where the backend runs)
    there is no mirror to remove.
    """
    if mirror is not None:
        try:
            mirror.remove(repository_id)
        except MirrorError as exc:
            with store.writer() as repos:
                repos.code_repositories.record_mirror_error(repository_id, CLEANUP_FAILED)
            raise Conflict(
                ERROR_TEXT[CLEANUP_FAILED] + ": the host still holds a file in it. Nothing else"
                " changed; Remove now tries again.",
                code=CLEANUP_FAILED,
                details={"leftover": f"repos/{repository_id}"},
            ) from exc
    with store.writer() as repos:
        repos.code_repositories.clear_mirror(repository_id)


def release_unlinked(
    store: RegistryUnitOfWork, mirror: MirrorControl | None, repository_ids: Iterable[str]
) -> list[str]:
    """Remove the mirror of each ``git_https`` repository among ``repository_ids`` that no board
    links any more; the ids whose mirror went, in the order given.

    A removal that fails is left on the row (``mirror_cleanup_failed``) for "Remove now"; it never
    fails the board edit that dropped the link.
    """
    candidates = list(dict.fromkeys(repository_ids))
    if mirror is None or not candidates:
        return []
    with store.reader() as repos:
        linked = {
            link.repository_id
            for selection in repos.repository_links.by_board().values()
            for link in selection
        }
        rows = [repos.code_repositories.get(repository_id) for repository_id in candidates]
    released: list[str] = []
    for row in rows:
        if row is None or row.provider != MIRRORED or row.id in linked:
            continue
        try:
            remove_mirror(store, mirror, row.id)
        except Conflict:
            continue
        logger.info("repository_mirror_released", extra={"repository_id": row.id})
        released.append(row.id)
    return released


def sweep(store: RegistryUnitOfWork, mirror: MirrorControl | None) -> list[str]:
    """Remove every mirror directory whose repository has no row; the ids that went.

    A cache the backend cannot list never stops it from starting: the failure is logged and the
    next start tries again.
    """
    if mirror is None:
        return []
    with store.reader() as repos:
        known = {row.id for row in repos.code_repositories.all()}
    try:
        return mirror.sweep_orphans(known)
    except OSError as exc:
        logger.warning("repository_mirror_sweep_failed", extra={"error": type(exc).__name__})
        return []
