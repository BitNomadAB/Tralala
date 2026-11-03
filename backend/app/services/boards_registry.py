"""A board's registry entry: the shape it is returned in, and the writes the board use cases share.

A new board's row is added in ``maintenance`` and turns ``active`` once its database is at the
schema head (``BoardSchema``); each use case records what it did in the board's own activity log.
The clock and the id source are passed in. ``BoardService`` (``services.boards``) and the archive
and idempotency use cases beside it call these, and ``services.boards`` re-exports the types.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypedDict, TypeIs

from pydantic import JsonValue

from ..core.context import ActorContext
from ..db.generated.registry import BoardsRow
from ..repositories.board import BoardRepositories
from ..repositories.board_rows import BoardChanges
from ..repositories.registry import RegistryUnitOfWork
from .activity import activity_entry

type Counts = tuple[int, int, int]
"""Open Loops, unarchived lists and unarchived cards, in that order."""

type JsonObject = dict[str, JsonValue]


class BoardEntry(TypedDict):
    """A board as the API returns it: the registry row, its counters and its selections."""

    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    archived_at: str | None
    schema_version: int
    schema_revision: str | None
    loop_count: int
    list_count: int
    card_count: int
    repository_ids: list[str]
    agent_ids: list[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class BoardSchema:
    """The head of the board migration chain, which a new board starts at."""

    head_revision: str
    version: int
    """The number of revisions in the chain, which the human-facing ``schema_version`` shows."""


def _is_object(value: object) -> TypeIs[JsonObject]:
    """A parsed JSON value that is an object: its keys are strings and its values JSON."""
    return isinstance(value, dict)


def json_object(value: object, what: str) -> JsonObject:
    """``value`` as a JSON object. Anything else raises the ``AttributeError`` that reading a key
    from it (``.get``) always raised, so a malformed archive fails exactly as before."""
    if not _is_object(value):
        raise AttributeError(f"{what} is not a JSON object")
    return value


def add_row(
    store: RegistryUnitOfWork,
    schema: BoardSchema,
    board_id: str,
    name: str,
    description: str,
    *,
    now: Callable[[], str],
) -> None:
    """A new board's registry row, in maintenance until its database is ready."""
    stamp = now()
    with store.writer() as repos:
        repos.boards.add(
            BoardsRow(
                id=board_id,
                name=name,
                description=description,
                status="maintenance",
                created_at=stamp,
                updated_at=stamp,
                archived_at=None,
                schema_version=schema.version,
                schema_revision=None,
            )
        )


def update_row(
    store: RegistryUnitOfWork, board_id: str, changes: BoardChanges, *, now: Callable[[], str]
) -> None:
    with store.writer() as repos:
        repos.boards.update(board_id, changes, now=now())


def activate(
    store: RegistryUnitOfWork, schema: BoardSchema, board_id: str, *, now: Callable[[], str]
) -> None:
    """The board's database is ready at the schema head, so the board takes requests."""
    update_row(
        store,
        board_id,
        {
            "status": "active",
            "schema_version": schema.version,
            "schema_revision": schema.head_revision,
        },
        now=now,
    )


def log_activity(
    board: BoardRepositories,
    actor: ActorContext,
    action: str,
    board_id: str,
    changes: Mapping[str, object] | None = None,
    *,
    new_id: Callable[[], str],
    now: Callable[[], str],
) -> None:
    board.activity.add(
        activity_entry(
            actor,
            action=action,
            entity_type="board",
            entity_id=board_id,
            changes=changes,
            entry_id=new_id(),
            timestamp=now(),
        )
    )
