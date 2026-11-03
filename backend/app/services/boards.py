"""Boards: each board's registry row, its database and files, its export and its import.

A board is a registry row (name, status, schema state) plus a directory with its own database and
its uploaded files. The service reaches the registry through the registry unit of work, a board's
database through the board unit of work (``app/repositories``) and its files through
``BoardFiles``; the clock, the id source and the schema head are passed in, so every rule here runs
in a unit test without a database.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal, Protocol, TypedDict, TypeIs
from uuid import uuid4

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..core.identifiers import canonical_board_id
from ..core.platform import copy_file, remove_file, remove_tree, retry_io
from ..db.generated.board import BoardLoopDefaultsRow, LabelsRow
from ..db.generated.registry import BoardsRow, IdempotencyRecordsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.board_files import BoardFiles, BoardMigrator, ProblemReason
from ..repositories.board_rows import BOARD_SORTS, BoardChanges
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.boards import BoardCreate, BoardUpdate
from .activity import activity_entry
from .common import archive_file_name
from .idempotency import request_fingerprint
from .templates import TemplateEntry

logger = logging.getLogger("tralala")

MANIFEST_MAX_BYTES = 1024 * 1024
EXPORT_FORMAT_VERSION = 2
MAX_ARCHIVE_ATTACHMENTS = 1000
ALLOWED_STATUSES = {"active", "archived", "maintenance", "error", "migration_failed"}

type Counts = tuple[int, int, int]
"""Open Loops, unarchived lists and unarchived cards, in that order."""

type JsonObject = dict[str, JsonValue]

type ImportRefusal = ProblemReason | Literal["migration_failed"]
"""Why an archive's database was refused: ``details.reason`` of ``422 board_import_invalid``."""

IMPORT_REFUSALS: Final[Mapping[ImportRefusal, str]] = {
    "not_a_database": "The archive's board.sqlite is not a database this installation can read",
    "integrity_check_failed": "Imported database failed integrity check",
    "not_a_board_database": "The archive's board.sqlite is not a board database",
    "unknown_schema_revision": (
        "The archive's board is at a schema revision this installation does not know"
    ),
    "migration_failed": "Imported board could not be migrated to the current schema",
}


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
    """What BoardService needs from RepositoryService: a board's repositories, checked and
    replaced."""

    def validate_ids(self, repository_ids: list[str]) -> None: ...

    def set_board_links(self, board_id: str, repository_ids: list[str]) -> None: ...


class TemplateResolver(Protocol):
    """What BoardService needs from TemplateService: the template a new board starts from."""

    def resolve(self, template_id: str) -> TemplateEntry: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def _is_object(value: object) -> TypeIs[JsonObject]:
    """A parsed JSON value that is an object: its keys are strings and its values JSON."""
    return isinstance(value, dict)


def _json_object(value: object, what: str) -> JsonObject:
    """``value`` as a JSON object. Anything else raises the ``AttributeError`` that reading a key
    from it (``.get``) always raised, so a malformed archive fails exactly as before."""
    if not _is_object(value):
        raise AttributeError(f"{what} is not a JSON object")
    return value


def _as_int(value: JsonValue) -> int:
    """``int()`` of a JSON scalar, as an archive manifest's numbers were always read."""
    if value is None or isinstance(value, (list, dict)):
        raise TypeError(f"not a number: {type(value).__name__}")
    return int(value)


def _archive_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """Read one member, refusing to expand past ``limit``.

    A zip's compression ratio is the attacker's choice: a few kilobytes can expand to gigabytes when
    read. The declared size is checked first and the real read is bounded, because a header can lie.
    """
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValidationFailure(
            "Board archive member is larger than this installation accepts",
            details={"entry": name, "bytes": info.file_size, "max_bytes": limit},
        )
    with archive.open(name) as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValidationFailure(
            "Board archive member is larger than this installation accepts",
            details={"entry": name, "max_bytes": limit},
        )
    return payload


def _refused(reason: ImportRefusal, detail: str) -> ValidationFailure:
    """The refusal of an archive whose database cannot become a board."""
    return ValidationFailure(
        IMPORT_REFUSALS[reason],
        code="board_import_invalid",
        details={"reason": reason, "detail": detail},
    )


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
        repository_map: Mapping[str, list[str]] | None = None,
        agent_map: Mapping[str, list[str]] | None = None,
    ) -> BoardEntry:
        if with_counts:
            counts = (count_map or {}).get(row.id) or self.stats.counts(row.id)
        else:
            counts = (0, 0, 0)
        loops, lists, cards = counts
        repository_ids = (
            repository_map.get(row.id, [])
            if repository_map is not None
            else self._repository_ids(row.id)
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
            "repository_ids": repository_ids,
            "agent_ids": agent_ids,
        }

    def _repository_ids(self, board_id: str) -> list[str]:
        with self.store.reader() as repos:
            return repos.repository_links.repository_ids(board_id)

    def _add_row(self, board_id: str, name: str, description: str) -> None:
        """A new board's registry row, in maintenance until its database is ready."""
        now = self._now()
        with self.store.writer() as repos:
            repos.boards.add(
                BoardsRow(
                    id=board_id,
                    name=name,
                    description=description,
                    status="maintenance",
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                    schema_version=self.schema.version,
                    schema_revision=None,
                )
            )

    def _update_row(self, board_id: str, changes: BoardChanges) -> None:
        with self.store.writer() as repos:
            repos.boards.update(board_id, changes, now=self._now())

    def _activate(self, board_id: str) -> None:
        """The board's database is ready at the schema head, so the board takes requests."""
        self._update_row(
            board_id,
            {
                "status": "active",
                "schema_version": self.schema.version,
                "schema_revision": self.schema.head_revision,
            },
        )

    def _log(
        self,
        board: BoardRepositories,
        actor: ActorContext,
        action: str,
        board_id: str,
        changes: Mapping[str, object] | None = None,
    ) -> None:
        board.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="board",
                entity_id=board_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
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
        if payload.repository_ids:
            self.repositories.validate_ids(list(payload.repository_ids))
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
                self.repositories.set_board_links(board_id, payload.repository_ids)
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
        """The answer a replayed key gets, or None after reserving the key for ``board_id``.

        The key is reserved before the board exists, so a retry that arrives while the first
        request is still creating it is told so instead of creating a second board.
        """
        with self.store.writer() as repos:
            existing = repos.idempotency.get(actor.actor_id, key)
            if existing is None:
                pending = {"_pending": True, "board_id": board_id}
                repos.idempotency.put(self._record(actor, key, fingerprint, pending))
                return None
            if existing.request_hash != fingerprint:
                raise Conflict(
                    "Idempotency key was already used with a different payload",
                    code="idempotency_key_reused",
                )
            stored = _json_object(json.loads(existing.response_json), "a stored response")
            if not stored.get("_pending"):
                return stored
            pending_id = str(stored.get("board_id") or "")
            row = repos.boards.get(pending_id) if pending_id else None
        if row is not None and row.status == "active":
            return self.serialize(row)
        if row is not None and row.status == "error":
            raise Conflict(
                "Board creation with this idempotency key failed; inspect the "
                "board entry before retrying",
                code="creation_failed",
                details={"board_id": pending_id},
            )
        raise Conflict(
            "Board creation is still in progress for this idempotency key",
            code="creation_in_progress",
            details={"board_id": pending_id},
        )

    def _record(
        self, actor: ActorContext, key: str, fingerprint: str, response: Mapping[str, object]
    ) -> IdempotencyRecordsRow:
        moment = self._clock()
        expires = moment + timedelta(seconds=self.settings.idempotency_ttl_seconds)
        return IdempotencyRecordsRow(
            actor_id=actor.actor_id,
            idempotency_key=key,
            request_hash=fingerprint,
            response_json=json.dumps(response),
            created_at=iso_utc(moment),
            expires_at=iso_utc(expires),
        )

    def _remember(
        self,
        actor: ActorContext,
        key: str | None,
        fingerprint: str,
        response: Mapping[str, object],
    ) -> None:
        if not key:
            return
        with self.store.writer() as repos:
            repos.idempotency.put(self._record(actor, key, fingerprint, response))

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
        if repository_ids is not None:
            self.repositories.validate_ids(list(repository_ids))
        agent_ids = payload.agent_ids
        if agent_ids is not None:
            self.agents.validate_ids(list(agent_ids))
        if not changes:
            self._relink(board_id, repository_ids, agent_ids)
            if repository_ids is not None or agent_ids is not None:
                return self.get(board_id)
            return self.serialize(row)
        self._update_row(board_id, changes)
        with self.boards.writer(board_id) as board:
            after = dict(changes)
            self._log(board, actor, "board.updated", board_id, {"before": before, "after": after})
        self._relink(board_id, repository_ids, agent_ids)
        return self.get(board_id)

    def _relink(
        self, board_id: str, repository_ids: list[str] | None, agent_ids: list[str] | None
    ) -> None:
        if repository_ids is not None:
            self.repositories.set_board_links(board_id, list(repository_ids))
        if agent_ids is not None:
            self.agents.set_board_agents(board_id, list(agent_ids))

    def archive(self, actor: ActorContext, board_id: str) -> BoardEntry:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if row.status == "archived":
            return self.serialize(row)
        self._update_row(board_id, {"status": "archived", "archived_at": self._now()})
        if self.boards.exists(board_id):
            with self.boards.writer(board_id) as board:
                self._log(board, actor, "board.archived", board_id)
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
        with self.store.writer() as repos:
            repos.boards.delete(board_id)

    # --- export / import -------------------------------------------------------------------------

    def export_archive(self, actor: ActorContext, board_id: str) -> bytes:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        attachments = self._attachment_files(board_id)
        manifest = {
            "format_version": EXPORT_FORMAT_VERSION,
            "exported_at": self._now(),
            "board": {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "schema_version": row.schema_version,
            },
            "attachments": {
                "files": len(attachments),
                "bytes": sum(file.stat().st_size for file in attachments),
            },
        }
        buffer = io.BytesIO()
        snapshot = self.files.path(board_id).with_suffix(".export.sqlite")
        profile = self.settings.file_profile
        try:
            self.files.snapshot(board_id, snapshot)
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                archive.write(snapshot, "board.sqlite")
                # The database and its uploaded files are one unit; an export without them is a
                # board that cannot be restored in full.
                for file in attachments:
                    retry_io(
                        "export_attachment",
                        profile,
                        lambda file=file: archive.write(file, f"attachments/{file.name}"),
                    )
        finally:
            remove_file(snapshot, profile=profile)
        return buffer.getvalue()

    def _copy_attachments(self, source_board_id: str, target_board_id: str) -> int:
        """A duplicated board keeps its uploaded files, or every attachment row points nowhere."""
        files = self._attachment_files(source_board_id)
        if not files:
            return 0
        directory = self.files.attachments_dir(target_board_id)
        directory.mkdir(parents=True, exist_ok=True)
        profile = self.settings.file_profile
        for file in files:
            copy_file(file, directory / file.name, profile=profile)
        return len(files)

    def _attachment_files(self, board_id: str) -> list[Path]:
        directory = self.files.attachments_dir(board_id)
        if not directory.exists():
            return []
        return sorted(file for file in directory.glob("*") if file.is_file())

    def import_archive(self, actor: ActorContext, data: bytes) -> BoardEntry:
        actor.require("boards:admin")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValidationFailure("Import payload is not a valid board archive") from exc
        with archive:
            names = set(archive.namelist())
            if not {"manifest.json", "board.sqlite"} <= names:
                raise ValidationFailure(
                    "Board archive must contain manifest.json and board.sqlite",
                    details={"found": sorted(names)},
                )
            manifest = _json_object(
                json.loads(_archive_member(archive, "manifest.json", MANIFEST_MAX_BYTES)),
                "the manifest",
            )
            if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
                raise ValidationFailure(
                    "Unsupported board archive format",
                    details={"supported": EXPORT_FORMAT_VERSION},
                )
            board_bytes = _archive_member(
                archive, "board.sqlite", int(self.settings.board_import_max_bytes)
            )
            attachment_entries = [
                entry
                for entry in archive.namelist()
                if entry.startswith("attachments/") and not entry.endswith("/")
            ]
            declared_files = _json_object(
                manifest.get("attachments") or {}, "the manifest's attachments"
            )
            declared = _as_int(declared_files.get("bytes") or 0)
            limit = int(self.settings.board_attachment_max_bytes)
            if declared > limit or len(attachment_entries) > MAX_ARCHIVE_ATTACHMENTS:
                raise ValidationFailure(
                    "Board archive carries more attachments than this installation accepts",
                    details={"bytes": declared, "files": len(attachment_entries)},
                )
            attachments: list[tuple[str, bytes]] = []
            seen: set[str] = set()
            total = 0
            for entry in attachment_entries:
                name = archive_file_name(entry)
                if name in seen:
                    raise ValidationFailure(
                        "Board archive contains an invalid attachment entry",
                        details={"entry": entry},
                    )
                seen.add(name)
                # The manifest is written by the exporter, so the real entries are measured too:
                # a hand-made archive could otherwise declare nothing and carry any amount.
                total += archive.getinfo(entry).file_size
                if total > limit:
                    raise ValidationFailure(
                        "Board archive carries more attachments than this installation accepts",
                        details={"bytes": total, "files": len(attachment_entries)},
                    )
                attachments.append((name, archive.read(entry)))

        new_id = self._new_id()
        board = _json_object(manifest.get("board", {}), "the manifest's board")
        name = str(board.get("name") or "Imported board")[:200]
        description = str(board.get("description") or "")[:20_000]
        try:
            self._accept_import(
                actor,
                new_id,
                name=name,
                description=description,
                database=board_bytes,
                attachments=attachments,
            )
        except Exception:
            self._discard_import(new_id)
            raise
        return self.get(new_id)

    def _accept_import(
        self,
        actor: ActorContext,
        board_id: str,
        *,
        name: str,
        description: str,
        database: bytes,
        attachments: list[tuple[str, bytes]],
    ) -> None:
        destination = self.files.path(board_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(database)
        # Judged before anything opens it, and before it has a row: a file that is not a sound
        # board database is never listed, recovered, migrated or opened as a board.
        problem = self.migrations.check_imported(board_id)
        if problem is not None:
            raise _refused(problem.reason, problem.detail)
        if attachments:
            directory = self.files.attachments_dir(board_id)
            directory.mkdir(parents=True, exist_ok=True)
            for file_name, payload in attachments:
                (directory / file_name).write_bytes(payload)
        self._add_row(board_id, name, description)
        # Migrated before it is opened: opening checks the revision, so an archive from an older
        # release is brought to the head first.
        if self.migrations.migrate_board(board_id).status == "failed":
            raise _refused("migration_failed", "the backend log names the cause")
        with self.boards.writer(board_id) as imported:
            imported.metadata.claim(board_id, now=self._now())
            changes = {"source_format": EXPORT_FORMAT_VERSION}
            self._log(imported, actor, "board.imported", board_id, changes)
        self._activate(board_id)

    def _discard_import(self, board_id: str) -> None:
        """Take away what a refused or failed import wrote: its files and the pre-migration backup
        the Migration Manager may have taken, then its row. An import is all or nothing.

        Files go first, as in ``delete``: when the host will not let go of one, the row stays,
        marked ``error``, so the leftover is visible and can be deleted later.
        """
        profile = self.settings.file_profile
        with self.store.reader() as repos:
            registered = repos.boards.get(board_id) is not None
        try:
            with self.files.locked(board_id):
                self.files.delete_database(board_id)
                remove_tree(self.settings.backups_dir / board_id, profile=profile)
        except OSError as exc:
            logger.warning(
                json.dumps(
                    {
                        "event": "board_import_leftover",
                        "board_id": board_id,
                        "leftover": f"boards/{board_id}",
                        "reason": type(exc).__name__,
                    }
                )
            )
            if registered:
                self._update_row(board_id, {"status": "error"})
            return
        if registered:
            with self.store.writer() as repos:
                repos.boards.delete(board_id)

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
