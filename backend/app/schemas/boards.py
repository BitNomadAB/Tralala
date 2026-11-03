from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints

from .common import Id, LongText, Name, OutModel, StrictModel

BoardStatus = Literal["active", "archived", "maintenance", "error", "migration_failed"]

MAX_GLOBS = 20
"""The most globs one list of a repository link may hold."""
MAX_GLOB_CHARS = 200
"""The longest glob, in characters."""
_DRIVE = re.compile(r"^[A-Za-z]:")


def relative_glob(glob: str) -> str:
    """A glob over the POSIX paths below a repository's root, as the snapshot reads them: never an
    absolute path, never a step out of the repository, and ``/`` between folders."""
    if "\\" in glob:
        raise ValueError("a glob separates folders with '/', never with a backslash")
    if glob.startswith("/") or _DRIVE.match(glob):
        raise ValueError("a glob is relative to the repository root, not an absolute path")
    if ".." in glob.split("/"):
        raise ValueError("a glob may not contain a '..' segment")
    return glob


Glob = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_GLOB_CHARS),
    AfterValidator(relative_glob),
]


class RepositoryPaths(StrictModel):
    """Which files of one linked repository a run's snapshot reads; both empty is all of them."""

    focus_paths: list[Glob] = Field(
        default_factory=list,
        max_length=MAX_GLOBS,
        description="When not empty, only files one of these globs matches are read",
    )
    exclude_paths: list[Glob] = Field(
        default_factory=list,
        max_length=MAX_GLOBS,
        description="Files one of these globs matches are never read",
    )


class BoardCreate(StrictModel):
    name: Name
    description: LongText = ""
    lists: list[Name] | None = Field(
        default=None, description="Optional initial list names; defaults to Backlog..Done"
    )
    template_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional saved template whose description, lists and labels are applied",
    )
    repository_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Repositories this board is about; chosen from the repository list",
    )
    repository_paths: dict[Id, RepositoryPaths] = Field(
        default_factory=dict,
        max_length=50,
        description="Focus and exclude globs by repository id; each id must be in repository_ids",
    )
    agent_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Agents that work on this board; chosen from the agent list",
    )


class BoardUpdate(StrictModel):
    name: Name | None = None
    description: LongText | None = None
    repository_ids: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Replace the board's repository selection; omit to keep it",
    )
    repository_paths: dict[Id, RepositoryPaths] | None = Field(
        default=None,
        max_length=50,
        description=(
            "Replace the globs of every linked repository (one without an entry reads all of it);"
            " omit to keep each kept repository's globs"
        ),
    )
    agent_ids: list[str] | None = Field(
        default=None,
        max_length=50,
        description="Replace the board's agent selection; omit to keep it",
    )


class RepositoryPathsOut(OutModel):
    focus_paths: list[str]
    exclude_paths: list[str]


class BoardOut(OutModel):
    id: str
    name: str
    description: str
    status: BoardStatus
    created_at: str
    updated_at: str
    archived_at: str | None = None
    schema_version: int
    schema_revision: str | None = None
    loop_count: int = 0
    list_count: int = 0
    card_count: int = 0
    repository_ids: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    repository_paths: dict[str, RepositoryPathsOut] = Field(
        default_factory=dict,
        description="The globs of each linked repository that has any; absent means all files",
    )


class BoardListOut(OutModel):
    items: list[BoardOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class BoardDelete(StrictModel):
    confirm_name: Name
