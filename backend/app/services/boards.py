from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core import sql
from ..core.config import Settings
from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..core.platform import copy_file, remove_file, remove_tree, retry_io
from ..schemas.boards import BoardCreate, BoardUpdate
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.schema import runner
from ..storage.sqlite import snapshot_database, utcnow
from .activity import log_activity
from .board_stats import BoardStatsCache
from .common import (
    archive_file_name,
    position_for_index,
    request_fingerprint,
    store_idempotency,
)

MANIFEST_MAX_BYTES = 1024 * 1024
EXPORT_FORMAT_VERSION = 2
BOARD_SCHEMA_VERSION = runner.revision_count("board")
ALLOWED_STATUSES = {"active", "archived", "maintenance", "error", "migration_failed"}
# What the board list formats into SQL text (see core/sql.py).
_BOARD_FILTERS: sql.Filters = (
    ("status", "status = :status"),
    ("q", "(name LIKE :q OR description LIKE :q)"),
)
_BOARD_SORTS = ("name", "status", "created_at", "updated_at")


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


def _require_intact(quick_check: str) -> None:
    if quick_check != "ok":
        raise ValidationFailure(
            "Imported database failed integrity check", details={"result": quick_check}
        )


def _require_migrated(status: str) -> None:
    if status == "failed":
        raise ValidationFailure(
            "Imported board could not be migrated to the current schema",
            details={"status": "migration_failed"},
        )


class BoardService:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        boards: BoardDatabaseManager,
        migrations: Any | None = None,
        templates: Any | None = None,
        stats: BoardStatsCache | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.boards = boards
        self.stats = stats or BoardStatsCache(settings, registry, boards)
        self.migrations = migrations
        self.templates = templates
        self.repositories: Any | None = None
        self.agents: Any | None = None

    # --- helpers ---------------------------------------------------------------

    def require_row(self, board_id: str) -> dict[str, Any]:
        board_id = self.boards.validate_board_id(board_id)
        row = self.registry.board(board_id)
        if row is None:
            raise NotFound("Board not found")
        return row

    def _resolve_template(self, template_id: str | None) -> dict[str, Any] | None:
        if not template_id:
            return None
        if self.templates is None:
            raise ValidationFailure(
                "Board templates are unavailable",
                details={"template_id": template_id},
            )
        return self.templates.resolve(template_id)

    def _counts(self, board_id: str) -> tuple[int, int, int]:
        return self.stats.counts(board_id)

    def serialize(
        self,
        row: dict[str, Any],
        *,
        with_counts: bool = True,
        count_map: dict[str, tuple[int, int, int]] | None = None,
        repository_map: dict[str, list[str]] | None = None,
        agent_map: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        entry = dict(row)
        entry.setdefault("schema_revision", None)
        if with_counts:
            counts = (count_map or {}).get(row["id"]) or self._counts(row["id"])
            entry["loop_count"], entry["list_count"], entry["card_count"] = counts
        else:
            entry.setdefault("loop_count", 0)
            entry.setdefault("list_count", 0)
            entry.setdefault("card_count", 0)
        entry["repository_ids"] = (
            repository_map[row["id"]]
            if repository_map is not None and row["id"] in repository_map
            else ([] if repository_map is not None else self._repository_ids(row["id"]))
        )
        entry["agent_ids"] = (
            agent_map[row["id"]]
            if agent_map is not None and row["id"] in agent_map
            else ([] if agent_map is not None else self._agent_ids(row["id"]))
        )
        return entry

    def _repository_ids(self, board_id: str) -> list[str]:
        return [
            record["repository_id"]
            for record in self.registry.read(
                "SELECT repository_id FROM board_repositories WHERE board_id = :id"
                " ORDER BY created_at, repository_id",
                {"id": board_id},
            )
        ]

    def _repository_ids_by_board(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for record in self.registry.read(
            "SELECT board_id, repository_id FROM board_repositories"
            " ORDER BY created_at, repository_id"
        ):
            grouped.setdefault(record["board_id"], []).append(record["repository_id"])
        return grouped

    def _agent_ids(self, board_id: str) -> list[str]:
        if self.agents is None:
            return []
        return self.agents.agent_ids(board_id)

    def _agent_ids_by_board(self) -> dict[str, list[str]]:
        return self.agents.agent_ids_for_boards() if self.agents is not None else {}

    # --- queries ---------------------------------------------------------------

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
    ) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {}
        if status:
            if status not in ALLOWED_STATUSES:
                raise ValidationFailure(
                    "Unknown board status",
                    details={"allowed": sorted(ALLOWED_STATUSES)},
                )
            params["status"] = status
        if q:
            params["q"] = f"%{q}%"
        where = sql.where(_BOARD_FILTERS, params)
        sort_column = sql.identifier(sort if sort in _BOARD_SORTS else "updated_at", _BOARD_SORTS)
        direction = "DESC" if order.lower() != "asc" else "ASC"
        total = self.registry.read_one(
            f"SELECT COUNT(*) AS total FROM boards{where}",  # noqa: S608 - from _BOARD_FILTERS
            params,
        )
        page = self.registry.read(
            "SELECT * FROM boards"  # noqa: S608 - from _BOARD_FILTERS and _BOARD_SORTS
            f"{where} ORDER BY {sort_column} {direction}, name LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        )
        repository_map = self._repository_ids_by_board()
        agent_map = self._agent_ids_by_board()
        # One lookup for the whole page: the counters come from the registry cache, so a board file
        # is only opened when its counters are missing or stale.
        count_map = self.stats.counts_for([row["id"] for row in page]) if with_counts else None
        return (
            [
                self.serialize(
                    row,
                    with_counts=with_counts,
                    count_map=count_map,
                    repository_map=repository_map,
                    agent_map=agent_map,
                )
                for row in page
            ],
            int(total["total"] if total else 0),
        )

    def get(self, board_id: str) -> dict[str, Any]:
        return self.serialize(self.require_row(board_id))

    # --- lifecycle -------------------------------------------------------------

    def create(
        self,
        actor: ActorContext,
        payload: BoardCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        actor.require("boards:write")
        template = self._resolve_template(payload.template_id)
        if payload.repository_ids:
            self.repositories.validate_ids(list(payload.repository_ids))
        if payload.agent_ids and self.agents is not None:
            self.agents.validate_ids(list(payload.agent_ids))
        fingerprint = request_fingerprint({"op": "board.create", "payload": payload.model_dump()})
        board_id = str(uuid4())
        if idempotency_key:
            with self.registry.connect() as conn:
                existing = (
                    conn.execute(
                        text(
                            "SELECT request_hash, response_json FROM idempotency_records"
                            " WHERE actor_id = :actor_id AND idempotency_key = :key"
                        ),
                        {"actor_id": actor.actor_id, "key": idempotency_key},
                    )
                    .mappings()
                    .first()
                )
                if existing is not None:
                    if existing["request_hash"] != fingerprint:
                        raise Conflict(
                            "Idempotency key was already used with a different payload",
                            code="idempotency_key_reused",
                        )
                    stored = json.loads(existing["response_json"])
                    if stored.get("_pending"):
                        pending_id = str(stored.get("board_id") or "")
                        row = self.registry.board(pending_id) if pending_id else None
                        if row and row["status"] == "active":
                            return self.serialize(row), True
                        if row and row["status"] == "error":
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
                    return stored, True
                store_idempotency(
                    conn,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    result={"_pending": True, "board_id": board_id},
                    ttl_seconds=self.settings.idempotency_ttl_seconds,
                )
        description = payload.description or (template["description"] if template else "")
        names = (
            payload.lists
            or (template["lists"] if template and template["lists"] else None)
            or self.settings.list_names
        )
        labels = list(template["labels"]) if template else []
        self.registry.insert_board(
            board_id,
            payload.name,
            description,
            "maintenance",
            BOARD_SCHEMA_VERSION,
        )
        try:
            self.boards.create_database(board_id, description)
            with self.boards.session(board_id) as conn:
                conn.execute(
                    text(
                        "INSERT INTO board_loop_defaults (id, column_names_json, updated_at)"
                        " VALUES (1, :names, :now)"
                    ),
                    {"names": json.dumps(names), "now": utcnow()},
                )
                for label in labels:
                    conn.execute(
                        text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)"),
                        {"id": str(uuid4()), "name": label["name"], "color": label["color"]},
                    )
                changes: dict[str, Any] = {
                    "name": payload.name,
                    "loop_columns": names,
                }
                if template is not None:
                    changes["template_id"] = template["id"]
                    changes["template_name"] = template["name"]
                log_activity(
                    conn,
                    actor,
                    action="board.created",
                    entity_type="board",
                    entity_id=board_id,
                    changes=changes,
                )
            # Links first: a crash before the board turns active leaves it in "maintenance", which
            # the dashboard shows, instead of an active board that silently analyses nothing.
            if payload.repository_ids:
                self.repositories.set_board_links(board_id, payload.repository_ids)
            if payload.agent_ids and self.agents is not None:
                self.agents.set_board_agents(board_id, payload.agent_ids)
            self.registry.update_board(
                board_id,
                status="active",
                schema_revision=runner.head_revision("board"),
                schema_version=runner.revision_count("board"),
            )
        except Exception:
            self.registry.update_board(board_id, status="error")
            with self.registry.connect() as conn:
                store_idempotency(
                    conn,
                    actor_id=actor.actor_id,
                    key=idempotency_key,
                    fingerprint=fingerprint,
                    result={"_pending": False, "board_id": board_id, "error": "creation_failed"},
                    ttl_seconds=self.settings.idempotency_ttl_seconds,
                )
            raise
        result = self.get(board_id)
        with self.registry.connect() as conn:
            store_idempotency(
                conn,
                actor_id=actor.actor_id,
                key=idempotency_key,
                fingerprint=fingerprint,
                result=result,
                ttl_seconds=self.settings.idempotency_ttl_seconds,
            )
        return result, False

    def update(self, actor: ActorContext, board_id: str, payload: BoardUpdate) -> dict[str, Any]:
        actor.require("boards:write")
        row = self.require_row(board_id)
        updates = payload.model_dump(exclude_none=True)
        repository_ids = updates.pop("repository_ids", None)
        if repository_ids is not None:
            self.repositories.validate_ids(list(repository_ids))
        agent_ids = updates.pop("agent_ids", None)
        if agent_ids is not None and self.agents is not None:
            self.agents.validate_ids(list(agent_ids))
        if not updates:
            if repository_ids is not None:
                self.repositories.set_board_links(board_id, list(repository_ids))
            if agent_ids is not None and self.agents is not None:
                self.agents.set_board_agents(board_id, list(agent_ids))
            if repository_ids is not None or agent_ids is not None:
                return self.get(board_id)
            return self.serialize(row)
        previous = {key: row[key] for key in updates}
        self.registry.update_board(board_id, **updates)
        with self.boards.session(board_id) as conn:
            log_activity(
                conn,
                actor,
                action="board.updated",
                entity_type="board",
                entity_id=board_id,
                changes={"before": previous, "after": updates},
            )
        if repository_ids is not None:
            self.repositories.set_board_links(board_id, list(repository_ids))
        if agent_ids is not None and self.agents is not None:
            self.agents.set_board_agents(board_id, list(agent_ids))
        return self.get(board_id)

    def archive(self, actor: ActorContext, board_id: str) -> dict[str, Any]:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if row["status"] == "archived":
            return self.serialize(row)
        self.registry.update_board(board_id, status="archived", archived_at=utcnow())
        if self.boards.exists(board_id):
            with self.boards.session(board_id) as conn:
                log_activity(
                    conn,
                    actor,
                    action="board.archived",
                    entity_type="board",
                    entity_id=board_id,
                )
        return self.get(board_id)

    def restore(self, actor: ActorContext, board_id: str) -> dict[str, Any]:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if row["status"] != "archived":
            raise Conflict("Only archived boards can be restored")
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        self.registry.update_board(board_id, status="active", archived_at=None)
        with self.boards.session(board_id) as conn:
            log_activity(
                conn,
                actor,
                action="board.restored",
                entity_type="board",
                entity_id=board_id,
            )
        return self.get(board_id)

    def duplicate(
        self, actor: ActorContext, board_id: str, name: str | None = None
    ) -> dict[str, Any]:
        actor.require("boards:write")
        source = self.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        new_id = str(uuid4())
        new_name = name or f"{source['name']} (copy)"
        self.registry.insert_board(
            new_id, new_name, source["description"], "maintenance", BOARD_SCHEMA_VERSION
        )
        try:
            snapshot_database(self.boards.path(board_id), self.boards.path(new_id))
            self._copy_attachments(board_id, new_id)
            with self.boards.session(new_id) as conn:
                conn.execute(
                    text("UPDATE board_metadata SET id = :id, updated_at = :now WHERE rowid = 1"),
                    {"id": new_id, "now": utcnow()},
                )
                log_activity(
                    conn,
                    actor,
                    action="board.duplicated",
                    entity_type="board",
                    entity_id=new_id,
                    changes={"source_board_id": board_id},
                )
            self.registry.update_board(
                new_id,
                status="active",
                schema_revision=runner.head_revision("board"),
                schema_version=runner.revision_count("board"),
            )
        except Exception:
            self.registry.update_board(new_id, status="error")
            raise
        return self.get(new_id)

    def delete(self, actor: ActorContext, board_id: str, confirm_name: str) -> None:
        actor.require("boards:admin")
        row = self.require_row(board_id)
        if row["status"] != "archived":
            raise Conflict("Archive the board before permanently deleting it")
        if confirm_name.strip() != row["name"]:
            raise ValidationFailure("Confirmation name does not match the board name")
        # Order matters: everything on disk goes first, so an interrupted delete leaves a row that
        # can be deleted again rather than a row pointing at files that no longer exist.
        profile = self.settings.file_profile
        with self.boards.locked(board_id):
            try:
                self.boards.delete_database(board_id)
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
        self.registry.delete_board_row(board_id)

    # --- export / import -------------------------------------------------------

    def export_archive(self, actor: ActorContext, board_id: str) -> bytes:
        actor.require("boards:write")
        row = self.require_row(board_id)
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        manifest = {
            "format_version": EXPORT_FORMAT_VERSION,
            "exported_at": utcnow(),
            "board": {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "schema_version": row["schema_version"],
            },
        }
        attachments = self._attachment_files(board_id)
        manifest["attachments"] = {
            "files": len(attachments),
            "bytes": sum(file.stat().st_size for file in attachments),
        }
        buffer = io.BytesIO()
        snapshot = self.boards.path(board_id).with_suffix(".export.sqlite")
        profile = self.settings.file_profile
        try:
            snapshot_database(self.boards.path(board_id), snapshot)
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
        directory = self.boards.attachments_dir(target_board_id)
        directory.mkdir(parents=True, exist_ok=True)
        profile = self.settings.file_profile
        for file in files:
            copy_file(file, directory / file.name, profile=profile)
        return len(files)

    def _attachment_files(self, board_id: str) -> list[Path]:
        directory = self.boards.attachments_dir(board_id)
        if not directory.exists():
            return []
        return sorted(file for file in directory.glob("*") if file.is_file())

    def import_archive(self, actor: ActorContext, data: bytes) -> dict[str, Any]:
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
            manifest = json.loads(_archive_member(archive, "manifest.json", MANIFEST_MAX_BYTES))
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
            declared = int((manifest.get("attachments") or {}).get("bytes") or 0)
            limit = int(self.settings.board_attachment_max_bytes)
            if declared > limit or len(attachment_entries) > 1000:
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

        new_id = str(uuid4())
        name = str(manifest.get("board", {}).get("name") or "Imported board")[:200]
        description = str(manifest.get("board", {}).get("description") or "")[:20_000]
        self.registry.insert_board(new_id, name, description, "maintenance", BOARD_SCHEMA_VERSION)
        try:
            destination = self.boards.path(new_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(board_bytes)
            if attachments:
                directory = self.boards.attachments_dir(new_id)
                directory.mkdir(parents=True, exist_ok=True)
                for name, payload in attachments:
                    (directory / name).write_bytes(payload)
            with self.boards.reader(new_id) as conn:
                _require_intact(conn.exec_driver_sql("PRAGMA quick_check").scalar_one())
            if self.migrations is not None:
                _require_migrated(self.migrations.migrate_board(new_id).status)
            with self.boards.session(new_id) as conn:
                conn.execute(
                    text("UPDATE board_metadata SET id = :id, updated_at = :now WHERE rowid = 1"),
                    {"id": new_id, "now": utcnow()},
                )
                log_activity(
                    conn,
                    actor,
                    action="board.imported",
                    entity_type="board",
                    entity_id=new_id,
                    changes={"source_format": EXPORT_FORMAT_VERSION},
                )
            self.registry.update_board(
                new_id,
                status="active",
                schema_revision=runner.head_revision("board"),
                schema_version=runner.revision_count("board"),
            )
        except Exception:
            self.registry.update_board(new_id, status="error")
            raise
        return self.get(new_id)

    # --- recovery --------------------------------------------------------------

    def recover(self) -> list[str]:
        """Repair registry rows left in an intermediate state by an interrupted operation."""
        recovered: list[str] = []
        for row in self.registry.read("SELECT * FROM boards WHERE status = 'maintenance'"):
            if self.boards.exists(row["id"]):
                self.registry.update_board(row["id"], status="active")
                recovered.append(row["id"])
            else:
                self.registry.update_board(row["id"], status="error")
                recovered.append(row["id"])
        return recovered

    # --- internals -------------------------------------------------------------

    def list_names(self) -> list[str]:
        return self.settings.list_names

    def ensure_active(self, board_id: str) -> dict[str, Any]:
        row = self.require_row(board_id)
        if row["status"] == "archived":
            raise Conflict("Board is archived", code="board_archived")
        if row["status"] == "migration_failed":
            raise Conflict(
                "Board migration failed; writes are blocked until it is repaired",
                code="board_migration_failed",
            )
        if row["status"] in {"maintenance", "error"}:
            raise Conflict("Board is not available", details={"status": row["status"]})
        if not self.boards.exists(board_id):
            raise NotFound("Board database not found")
        return row

    def default_position(self, board_id: str, loop_id: str) -> int:
        with self.boards.reader(board_id) as conn:
            return position_for_index(conn, "lists", {"loop_id": loop_id}, None)
