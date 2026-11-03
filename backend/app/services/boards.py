"""Boards: each board's registry row, its database and files, its export and its import.

A board is a registry row (name, status, schema state) plus a directory with its own database and
its uploaded files. The service reaches the registry through the registry unit of work, a board's
database through the board unit of work (``app/repositories``) and its files through
``BoardFiles``; the clock, the id source and the schema head are passed in, so every rule here runs
in a unit test without a database.

This module is the public import path. ``BoardService`` keeps the queries, the lifecycle and the
checks other services use, and delegates the use cases that live beside it: the registry entry and
activity writes they share (``boards_registry``), replaying a creation (``boards_idempotency``) and
export and import (``boards_archive``), whose names it re-exports.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailure
from ..core.identifiers import canonical_board_id
from ..core.platform import remove_tree
from ..db.generated.board import BoardLoopDefaultsRow, LabelsRow
from ..db.generated.registry import BoardRepositoriesRow, BoardsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.board_files import BoardFiles, BoardMigrator
from ..repositories.board_rows import BOARD_SORTS, BoardChanges
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.boards import BoardCreate, BoardUpdate, RepositoryPaths
from . import boards_archive, boards_idempotency, boards_registry
from .boards_archive import (
    EXPORT_FORMAT_VERSION,
    IMPORT_REFUSALS,
    MANIFEST_MAX_BYTES,
    MAX_ARCHIVE_ATTACHMENTS,
    ImportRefusal,
)
from .boards_registry import BoardEntry, BoardSchema, Counts, JsonObject
from .idempotency import request_fingerprint
from .repository_links import paths_by_repository
from .templates import TemplateEntry

logger = logging.getLogger("tralala")

ALLOWED_STATUSES = {"active", "archived", "maintenance", "error", "migration_failed"}


class BoardCounters(Protocol):
    """The dashboard counters (``BoardStatsCache``)."""

    def counts(self, board_id: str) -> Counts: ...

    def counts_for(self, board_ids: list[str]) -> dict[str, Counts]: ...


class AgentSelection(Protocol):
    """What BoardService needs from AgentService: a board's agents, checked and replaced."""

    def validate_ids(self, agent_ids: list[str]) -> None: ...

    def set_board_agents(self, board_id: str, agent_ids: list[str]) -> None: ...

    def agent_ids(self, board_id: str) -> list[str]: ...

    def agent_ids_for_boards(self) -> dict[str, list[str]]: ...


class RepositorySelection(Protocol):
    """What BoardService needs from RepositoryService: a board's repositories and their globs,
    checked and replaced."""

    def validate_ids(
        self, repository_ids: list[str], paths: Mapping[str, RepositoryPaths] | None = None
    ) -> None: ...

    def set_board_links(
        self,
        board_id: str,
        repository_ids: list[str],
        paths: Mapping[str, RepositoryPaths] | None = None,
    ) -> None: ...


class TemplateResolver(Protocol):
    """What BoardService needs from TemplateService: the template a new board starts from."""

    def resolve(self, template_id: str) -> TemplateEntry: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class BoardService:
    def __init__(
        self,
        settings: Settings,
        store: RegistryUnitOfWork,
        boards: BoardUnitOfWork,
        files: BoardFiles,
        *,
        migrations: BoardMigrator,
        schema: BoardSchema,
        stats: BoardCounters,
        agents: AgentSelection,
        repositories: RepositorySelection,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.settings = settings
        self.store = store
        self.boards = boards
        self.files = files
        self.migrations = migrations
        self.schema = schema
        self.stats = stats
        self.agents = agents
        self.repositories = repositories
        # TemplateService looks boards up through this service, so the composition root sets it.
        self.templates: TemplateResolver | None = None
        self._clock = clock
        self._new_id = new_id

    # --- helpers ---------------------------------------------------------------------------------

    def _now(self) -> str:
        return iso_utc(self._clock())

    def require_row(self, board_id: str) -> BoardsRow:
        board_id = canonical_board_id(board_id)
        with self.store.reader() as repos:
            row = repos.boards.get(board_id)
        if row is None:
            raise NotFound("Board not found")
        return row

    def _resolve_template(self, template_id: str | None) -> TemplateEntry | None:
        if not template_id:
            return None
        if self.templates is None:
            raise ValidationFailure(
                "Board templates are unavailable",
                details={"template_id": template_id},
            )
        return self.templates.resolve(template_id)

    def serialize(
        self,
        row: BoardsRow,
        *,
        with_counts: bool = True,
        count_map: Mapping[str, Counts] | None = None,
        repository_map: Mapping[str, list[BoardRepositoriesRow]] | None = None,
        agent_map: Mapping[str, list[str]] | None = None,
    ) -> BoardEntry:
        if with_counts:
            counts = (count_map or {}).get(row.id) or self.stats.counts(row.id)
        else:
            counts = (0, 0, 0)
        loops, lists, cards = counts
        links = (
            repository_map.get(row.id, [])
            if repository_map is not None
            else self._repository_links(row.id)
        )
        agent_ids = (
            agent_map.get(row.id, []) if agent_map is not None else self.agents.agent_ids(row.id)
        )
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "archived_at": row.archived_at,
            "schema_version": row.schema_version,
            "schema_revision": row.schema_revision,
            "loop_count": loops,
            "list_count": lists,
            "card_count": cards,
            "repository_ids": [link.repository_id for link in links],
            "agent_ids": agent_ids,
            "repository_paths": paths_by_repository(links),
        }

    def _repository_links(self, board_id: str) -> list[BoardRepositoriesRow]:
        with self.store.reader() as repos:
            return repos.repository_links.links(board_id)

    def _add_row(self, board_id: str, name: str, description: str) -> None:
        """A new board's registry row, in maintenance until its database is ready."""
        boards_registry.add_row(self.store, self.schema, board_id, name, description, now=self._now)

    def _update_row(self, board_id: str, changes: BoardChanges) -> None:
        boards_registry.update_row(self.store, board_id, changes, now=self._now)

    def _activate(self, board_id: str) -> None:
        """The board's database is ready at the schema head, so the board takes requests."""
        boards_registry.activate(self.store, self.schema, board_id, now=self._now)

    def _log(
        self,
        board: BoardRepositories,
        actor: ActorContext,
        action: str,
        board_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        boards_registry.log_activity(
            board, actor, action, board_id, changes, new_id=self._new_id, now=self._now
        )

    # --- queries ---------------------------------------------------------------------------------

    def list(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        sort: str = "updated_at",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
        with_counts: bool = True,
    ) -> tuple[list[BoardEntry], int]:
        if status and status not in ALLOWED_STATUSES:
            raise ValidationFailure(
                "Unknown board status",
                details={"allowed": sorted(ALLOWED_STATUSES)},
            )
        with self.store.reader() as repos:
            total = repos.boards.count(status=status or None, contains=q or None)
            page = repos.boards.page(
                status=status or None,
                contains=q or None,
                sort=sort if sort in BOARD_SORTS else "updated_at",
                descending=order.lower() != "asc",
                limit=limit,
                offset=offset,
            )
            repository_map = repos.repository_links.by_board()
        agent_map = self.agents.agent_ids_for_boards()
        # One lookup for the whole page: the counters come from the registry cache, so a board file
        # is only opened when its counters are missing or stale.
        count_map = self.stats.counts_for([row.id for row in page]) if with_counts else None
        entries = [
            self.serialize(
                row,
                with_counts=with_counts,
                count_map=count_map,
                repository_map=repository_map,
                agent_map=agent_map,
            )
            for row in page
        ]
        return entries, total

    def get(self, board_id: str) -> BoardEntry:
        return self.serialize(self.require_row(board_id))

    # --- lifecycle -------------------------------------------------------------------------------

    def create(
        self,
        actor: ActorContext,
        payload: BoardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[BoardEntry | JsonObject, bool]:
        """The new board and False, or the answer stored for a replayed key and True."""
        actor.require("boards:write")
        template = self._resolve_template(payload.template_id)
        if payload.repository_ids or payload.repository_paths:
            self.repositories.validate_ids(list(payload.repository_ids), payload.repository_paths)
        if payload.agent_ids:
            self.agents.validate_ids(list(payload.agent_ids))
        fingerprint = request_fingerprint({"op": "board.create", "payload": payload.model_dump()})
        board_id = self._new_id()
        if idempotency_key:
            replayed = self._replay_or_reserve(actor, idempotency_key, fingerprint, board_id)
            if replayed is not None:
                return replayed, True
        description = payload.description or (template["description"] if template else "")
        names = (
            payload.lists
            or (template["lists"] if template and template["lists"] else None)
            or self.settings.list_names
        )
        labels = list(template["labels"]) if template else []
        self._add_row(board_id, payload.name, description)
        try:
            self.files.create_database(board_id, description)
            with self.boards.writer(board_id) as board:
                board.loop_defaults.add(
                    BoardLoopDefaultsRow(
                        id=1, column_names_json=json.dumps(names), updated_at=self._now()
                    )
                )
                for label in labels:
                    board.labels.add(
                        LabelsRow(id=self._new_id(), name=label["name"], color=label["color"])
                    )
                changes: dict[str, object] = {"name": payload.name, "loop_columns": names}
                if template is not None:
                    changes["template_id"] = template["id"]
                    changes["template_name"] = template["name"]
                self._log(board, actor, "board.created", board_id, changes)
            # Links first: a crash before the board turns active leaves it in "maintenance", which
            # the dashboard shows, instead of an active board that silently analyses nothing.
            if payload.repository_ids:
                self.repositories.set_board_links(
                    board_id, payload.repository_ids, payload.repository_paths
                )
            if payload.agent_ids:
                self.agents.set_board_agents(board_id, payload.agent_ids)
            self._activate(board_id)
        except Exception:
            self._update_row(board_id, {"status": "error"})
            failure = {"_pending": False, "board_id": board_id, "error": "creation_failed"}
            self._remember(actor, idempotency_key, fingerprint, failure)
            raise
        result = self.get(board_id)
        self._remember(actor, idempotency_key, fingerprint, result)
        return result, False

    def _replay_or_reserve(
        self, actor: ActorContext, key: str, fingerprint: str, board_id: str
    ) -> BoardEntry | JsonObject | None:
        return boards_idempotency.replay_or_reserve(
            self.store,
            self.settings,
            actor,
            key,
            fingerprint,
            board_id,
            clock=self._clock,
            serialize=self.serialize,
        )

    def _remember(
        self,
        actor: ActorContext,
        key: str | None,
        fingerprint: str,
        response: Mapping[str, object],
    ) -> None:
        boards_idempotency.remember(
            self.store, self.settings, actor, key, fingerprint, response, clock=self._clock
        )

    def update(self, actor: ActorContext, board_id: str, payload: BoardUpdate) -> BoardEntry:
        actor.require("boards:write")
        row = self.require_row(board_id)
        changes: BoardChanges = {}
        before: dict[str, str] = {}
        if payload.name is not None:
            changes["name"] = payload.name
            before["name"] = row.name
        if payload.description is not None:
            changes["description"] = payload.description
            before["description"] = row.description
        repository_ids = payload.repository_ids
        paths = payload.repository_paths
        if repository_ids is None and paths is not None:
            # Globs alone keep the selection and replace the globs of the links the board has.
            repository_ids = [link.repository_id for link in self._repository_links(board_id)]
        if repository_ids is not None:
            self.repositories.validate_ids(list(repository_ids), paths)
        agent_ids = payload.agent_ids
        if agent_ids is not None:
            self.agents.validate_ids(list(agent_ids))
        if not changes:
            self._relink(board_id, repository_ids, agent_ids, paths)
            if repository_ids is not None or agent_ids is not None:
                return self.get(board_id)
            return self.serialize(row)
        self._update_row(board_id, changes)
        with self.boards.writer(board_id) as board:
            after = dict(changes)
            self._log(board, actor, "board.updated", board_id, {"before": before, "after": after})
        self._relink(board_id, repository_ids, agent_ids, paths)
        return self.get(board_id)

    def _relink(
        self,
        board_id: str,
        repository_ids: list[str] | None,
        agent_ids: list[str] | None,
        paths: Mapping[str, RepositoryPaths] | None,
    ) -> None:
        if repository_ids is not None:
            self.repositories.set_board_links(board_id, list(repository_ids), paths)
        if agent_ids is not None:
            self.agents.set_board_agents(board_id, list(agent_ids))

    def archive(self, actor: ActorContext, board_id: str) -> BoardEntry:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if row.status == "archived":
            return self.serialize(row)
        self._update_row(board_id, {"status": "archived", "archived_at": self._now()})
        if self.boards.exists(board_id):
            try:
                with self.boards.writer(board_id) as board:
                    self._log(board, actor, "board.archived", board_id)
            except ServiceUnavailable as exc:
                # The archive is the registry's decision and is already made. A board whose
                # database cannot be opened (unreadable, or not at the schema head) has to be
                # archivable, because archiving is the way to delete it; only the board's own
                # record of the archive is missing, and the log says so.
                logger.error(
                    exc.code, extra={"board_id": board_id, "skipped": "board_archived_activity"}
                )
        return self.get(board_id)

    def restore(self, actor: ActorContext, board_id: str) -> BoardEntry:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if row.status != "archived":
            raise Conflict("Only archived boards can be restored")
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        self._update_row(board_id, {"status": "active", "archived_at": None})
        with self.boards.writer(board_id) as board:
            self._log(board, actor, "board.restored", board_id)
        return self.get(board_id)

    def duplicate(self, actor: ActorContext, board_id: str, name: str | None = None) -> BoardEntry:
        actor.require("boards:write")
        source = self.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        new_id = self._new_id()
        self._add_row(new_id, name or f"{source.name} (copy)", source.description)
        try:
            self.files.snapshot(board_id, self.files.path(new_id))
            self._copy_attachments(board_id, new_id)
            with self.boards.writer(new_id) as board:
                board.metadata.claim(new_id, now=self._now())
                changes = {"source_board_id": board_id}
                self._log(board, actor, "board.duplicated", new_id, changes)
            self._activate(new_id)
        except Exception:
            self._update_row(new_id, {"status": "error"})
            raise
        return self.get(new_id)

    def delete(self, actor: ActorContext, board_id: str, confirm_name: str) -> None:
        actor.require("boards:admin")
        row = self.require_row(board_id)
        if row.status != "archived":
            raise Conflict("Archive the board before permanently deleting it")
        if confirm_name.strip() != row.name:
            raise ValidationFailure("Confirmation name does not match the board name")
        # Order matters: everything on disk goes first, so an interrupted delete leaves a row that
        # can be deleted again rather than a row pointing at files that no longer exist.
        profile = self.settings.file_profile
        with self.files.locked(board_id):
            try:
                self.files.delete_database(board_id)
                remove_tree(self.settings.backups_dir / board_id, profile=profile)
            except OSError as exc:
                # The board survives on purpose: it still has data, and the operator can retry once
                # whatever held the file has let go. Naming the leftover directory is the useful
                # part, and it is relative so the response stays free of absolute paths.
                raise Conflict(
                    "The board's files could not all be removed, so the board was not deleted",
                    code="board_files_busy",
                    details={
                        "leftover": f"boards/{board_id}",
                        "backups_leftover": f"backups/{board_id}",
                        "reason": type(exc).__name__,
                        "errno": getattr(exc, "errno", None),
                        "winerror": getattr(exc, "winerror", None),
                        "platform_profile": profile,
                    },
                ) from exc
        # The links go first, through the repository service, so a mirrored repository this was
        # the last board of loses its mirror too.
        self.repositories.set_board_links(row.id, [])
        with self.store.writer() as repos:
            repos.boards.delete(board_id)

    # --- export / import -------------------------------------------------------------------------

    def export_archive(self, actor: ActorContext, board_id: str) -> bytes:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        return boards_archive.export_archive(
            self.files, self.settings, board_id, row, now=self._now
        )

    def _copy_attachments(self, source_board_id: str, target_board_id: str) -> int:
        return boards_archive.copy_attachments(
            self.files, self.settings, source_board_id, target_board_id
        )

    def import_archive(self, actor: ActorContext, data: bytes) -> BoardEntry:
        board_id = boards_archive.import_archive(
            actor,
            data,
            settings=self.settings,
            store=self.store,
            boards=self.boards,
            files=self.files,
            migrations=self.migrations,
            schema=self.schema,
            now=self._now,
            new_id=self._new_id,
        )
        return self.get(board_id)

    # --- recovery --------------------------------------------------------------------------------

    def recover(self) -> list[str]:
        """Repair registry rows left in an intermediate state by an interrupted operation."""
        with self.store.reader() as repos:
            interrupted = repos.boards.with_status("maintenance")
        recovered: list[str] = []
        for row in interrupted:
            status = "active" if self.boards.exists(row.id) else "error"
            self._update_row(row.id, {"status": status})
            recovered.append(row.id)
        return recovered

    # --- checks other services use ---------------------------------------------------------------

    def ensure_active(self, board_id: str) -> BoardsRow:
        row = self.require_row(board_id)
        if row.status == "archived":
            raise Conflict("Board is archived", code="board_archived")
        if row.status == "migration_failed":
            raise Conflict(
                "Board migration failed; writes are blocked until it is repaired",
                code="board_migration_failed",
            )
        if row.status in {"maintenance", "error"}:
            raise Conflict("Board is not available", details={"status": row.status})
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        return row


__all__ = [
    "ALLOWED_STATUSES",
    "EXPORT_FORMAT_VERSION",
    "IMPORT_REFUSALS",
    "MANIFEST_MAX_BYTES",
    "MAX_ARCHIVE_ATTACHMENTS",
    "AgentSelection",
    "BoardCounters",
    "BoardEntry",
    "BoardSchema",
    "BoardService",
    "Counts",
    "ImportRefusal",
    "JsonObject",
    "RepositorySelection",
    "TemplateResolver",
]
