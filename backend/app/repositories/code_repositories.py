"""Code repositories (the ``repositories`` table) and the boards that link them.

The registry keeps one list of repositories; a board links the ones it is about through a row per
repository in ``board_repositories``. A repository's access token is stored sealed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Required, TypedDict

from ..db.generated.registry import BoardRepositoriesRow, BoardsRow, RepositoriesRow

# The columns of ``RepositoryChanges``, as an edit formats them into its SQL text (core/sql.py).
REPOSITORY_EDITABLE = (
    "name",
    "url",
    "branch",
    "enabled",
    "token_ciphertext",
    "token_hint",
    "updated_at",
)


class RepositoryChanges(TypedDict, total=False):
    """The columns an edit writes; ``updated_at`` always changes, even when nothing else does."""

    name: str
    url: str
    branch: str | None
    enabled: int
    token_ciphertext: str | None
    token_hint: str | None
    updated_at: Required[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class MirrorRecord:
    """What a good fetch of a repository's Git mirror leaves on its row."""

    default_branch: str | None
    """The branch the remote's HEAD named; None keeps the one stored (an explicit branch was
    fetched, so the remote was not asked)."""
    last_sha: str
    fetched_at: str
    mirror_bytes: int


@dataclass(frozen=True, slots=True, kw_only=True)
class LinkedBoard:
    """A board's link to a repository, with the board."""

    link: BoardRepositoriesRow
    board: BoardsRow


class CodeRepositoryRepository(Protocol):
    def get(self, repository_id: str) -> RepositoriesRow | None: ...

    def all(self) -> list[RepositoriesRow]:
        """By name (case-insensitive), then id."""
        ...

    def for_board(self, board_id: str) -> list[RepositoriesRow]:
        """The repositories the board links, in the order of ``all``."""
        ...

    def url_taken(self, url: str, *, other_than: str | None = None) -> bool:
        """Whether a repository other than ``other_than`` has exactly this URL."""
        ...

    def add(self, row: RepositoriesRow) -> None: ...

    def update(self, repository_id: str, changes: RepositoryChanges) -> None: ...

    def record_check(self, repository_id: str, *, status: str, detail: str, now: str) -> None:
        """The outcome of the last access check; ``updated_at`` becomes ``now`` too."""
        ...

    def record_default_branch(self, repository_id: str, default_branch: str) -> None:
        """The branch the remote's HEAD names, as an access check found it."""
        ...

    def record_fetch(self, repository_id: str, record: MirrorRecord) -> None:
        """A good fetch of the mirror; it clears ``mirror_error``."""
        ...

    def record_mirror_error(self, repository_id: str, code: str) -> None:
        """Why the last fetch failed; what the last good fetch recorded stays."""
        ...

    def delete(self, repository_id: str) -> None:
        """Delete the repository; the boards that linked it lose the link."""
        ...

    def sealed_tokens(self) -> dict[str, str]:
        """The sealed token of every repository that has one, by repository id."""
        ...

    def reseal(self, repository_id: str, ciphertext: str, *, now: str) -> None:
        """Replace the sealed token and set ``updated_at``."""
        ...


class RepositoryLinkRepository(Protocol):
    """The repositories each board links (``board_repositories``)."""

    def linked_boards(self) -> list[LinkedBoard]:
        """Every link with its board, by board name (case-insensitive)."""
        ...

    def repository_ids(self, board_id: str) -> list[str]:
        """The board's repositories in the order they were linked (then by id)."""
        ...

    def by_board(self) -> dict[str, list[str]]:
        """Every board's repositories, each in the order of ``repository_ids``."""
        ...

    def clear(self, board_id: str) -> None: ...

    def add(self, row: BoardRepositoriesRow) -> None: ...
