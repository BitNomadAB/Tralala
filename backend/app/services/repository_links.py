"""A board's links to its repositories, and the globs that steer what each link's snapshot reads.

``board_repositories`` holds one row per repository a board is about, with two JSON arrays of
globs: ``focus_paths`` (when not empty, only the files they match are read) and ``exclude_paths``
(the files they match are never read). A request's globs are validated where it enters
(``schemas/boards.py``) and matched by the snapshot (``repo_snapshot.select_members``); here they
are written, read back and named. ``RepositoryService`` delegates a board's links to these
functions, which reach the registry only through its unit of work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TypedDict

from pydantic import JsonValue

from ..core.errors import ValidationFailure
from ..db.generated.registry import BoardRepositoriesRow
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.boards import RepositoryPaths

NO_GLOBS = "[]"


class LinkPaths(TypedDict):
    """The globs of one link, as a board returns them and a snapshot applies them."""

    focus_paths: list[str]
    exclude_paths: list[str]


def encode_globs(globs: Sequence[str]) -> str:
    """The column's JSON text: an array of strings, ``[]`` for none."""
    return json.dumps(list(globs), ensure_ascii=False)


def decode_globs(text: str) -> list[str]:
    """The globs a column holds: a value that is not an array reads as none, and an item that is
    not a string is left out."""
    value: JsonValue = json.loads(text or NO_GLOBS)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def link_paths(link: BoardRepositoriesRow) -> LinkPaths:
    return {
        "focus_paths": decode_globs(link.focus_paths),
        "exclude_paths": decode_globs(link.exclude_paths),
    }


def paths_by_repository(links: Sequence[BoardRepositoriesRow]) -> dict[str, LinkPaths]:
    """A board's ``repository_paths``: the globs of each link that has any, by repository id."""
    found = {link.repository_id: link_paths(link) for link in links}
    return {
        repository_id: paths
        for repository_id, paths in found.items()
        if paths["focus_paths"] or paths["exclude_paths"]
    }


def require_selected(
    repository_ids: Sequence[str], paths: Mapping[str, RepositoryPaths] | None
) -> None:
    """Globs belong to a link: an id in ``paths`` that the selection does not hold is refused."""
    unselected = sorted(set(paths or {}) - set(repository_ids))
    if unselected:
        raise ValidationFailure(
            "Paths are given for a repository the board does not link",
            details={"field": "repository_paths", "repository_ids": unselected},
        )


def replace_links(
    store: RegistryUnitOfWork,
    board_id: str,
    repository_ids: Sequence[str],
    paths: Mapping[str, RepositoryPaths] | None,
    *,
    now: str,
) -> list[str]:
    """Replace a board's links and answer the repositories the board no longer links. ``paths``
    gives every link its globs (a repository without an entry reads all of it); ``None`` keeps the
    globs of each repository that stays linked, so a caller that only sends ``repository_ids``
    loses nothing."""
    with store.writer() as repos:
        kept = {link.repository_id: link for link in repos.repository_links.links(board_id)}
        repos.repository_links.clear(board_id)
        for repository_id in dict.fromkeys(repository_ids):
            focus, exclude = _stored_globs(repository_id, paths, kept)
            repos.repository_links.add(
                BoardRepositoriesRow(
                    board_id=board_id,
                    repository_id=repository_id,
                    created_at=now,
                    focus_paths=focus,
                    exclude_paths=exclude,
                )
            )
    return [repository_id for repository_id in kept if repository_id not in repository_ids]


def _stored_globs(
    repository_id: str,
    paths: Mapping[str, RepositoryPaths] | None,
    kept: Mapping[str, BoardRepositoriesRow],
) -> tuple[str, str]:
    """The focus and exclude columns of one new link."""
    if paths is None:
        link = kept.get(repository_id)
        return (link.focus_paths, link.exclude_paths) if link else (NO_GLOBS, NO_GLOBS)
    chosen = paths.get(repository_id)
    if chosen is None:
        return NO_GLOBS, NO_GLOBS
    return encode_globs(chosen.focus_paths), encode_globs(chosen.exclude_paths)
