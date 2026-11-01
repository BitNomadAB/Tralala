from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailure
from ..schemas.boards import BoardCreate, BoardUpdate
from ..storage.board_db import BoardDatabaseManager
from ..storage.registry import Registry
from ..storage.schema import runner
from ..storage.sqlite import snapshot_database, utcnow
from .activity import log_activity
from .common import (
    position_for_index,
    request_fingerprint,
    store_idempotency,
)

EXPORT_FORMAT_VERSION = 1
BOARD_SCHEMA_VERSION = runner.revision_count("board")
ALLOWED_STATUSES = {"active", "archived", "maintenance", "error", "migration_failed"}


class BoardService:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        boards: BoardDatabaseManager,
        migrations: Any | None = None,
        templates: Any | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.boards = boards
        self.migrations = migrations
        self.templates = templates

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

    def _counts(self, board_id: str) -> tuple[int, int]:
        try:
            with self.boards.reader(board_id) as conn:
                lists = conn.execute(
                    text("SELECT COUNT(*) FROM lists WHERE archived_at IS NULL")
                ).scalar_one()
                cards = conn.execute(
                    text("SELECT COUNT(*) FROM cards WHERE archived_at IS NULL")
                ).scalar_one()
            return int(lists), int(cards)
        except (NotFound, ServiceUnavailable):
            # A board whose schema is mid-repair must still appear in the dashboard.
            return 0, 0

    def serialize(self, row: dict[str, Any], *, with_counts: bool = True) -> dict[str, Any]:
        entry = dict(row)
        entry.setdefault("schema_revision", None)
        if with_counts:
            entry["list_count"], entry["card_count"] = self._counts(row["id"])
        else:
            entry.setdefault("list_count", 0)
            entry.setdefault("card_count", 0)
        return entry

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
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if status:
            if status not in ALLOWED_STATUSES:
                raise ValidationFailure(
                    "Unknown board status",
                    details={"allowed": sorted(ALLOWED_STATUSES)},
                )
            clauses.append("status = :status")
            params["status"] = status
        if q:
            clauses.append("(name LIKE :q OR description LIKE :q)")
            params["q"] = f"%{q}%"
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sort_column = (
            sort if sort in {"name", "status", "created_at", "updated_at"} else "updated_at"
        )
        direction = "DESC" if order.lower() != "asc" else "ASC"
        total = self.registry.read_one(f"SELECT COUNT(*) AS total FROM boards{where}", params)
        page = self.registry.read(
            f"SELECT * FROM boards{where}"
            f" ORDER BY {sort_column} {direction}, name"
            " LIMIT :limit OFFSET :offset",
            {**params, "limit": limit, "offset": offset},
        )
        return [self.serialize(row) for row in page], int(total["total"] if total else 0)

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
                for index, name in enumerate(names):
                    conn.execute(
                        text(
                            "INSERT INTO lists (id, name, position, created_at, updated_at)"
                            " VALUES (:id, :name, :position, :now, :now)"
                        ),
                        {
                            "id": str(uuid4()),
                            "name": name,
                            "position": (index + 1) * 1024,
                            "now": utcnow(),
                        },
                    )
                for label in labels:
                    conn.execute(
                        text("INSERT INTO labels (id, name, color) VALUES (:id, :name, :color)"),
                        {"id": str(uuid4()), "name": label["name"], "color": label["color"]},
                    )
                changes: dict[str, Any] = {"name": payload.name, "lists": names}
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
        if not updates:
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
        self.boards.delete_database(board_id)
        backup_dir = self.settings.backups_dir / board_id
        if backup_dir.exists():
            for file in backup_dir.iterdir():
                if file.is_file():
                    file.unlink()
            backup_dir.rmdir()
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
        buffer = io.BytesIO()
        snapshot = self.boards.path(board_id).with_suffix(".export.sqlite")
        try:
            snapshot_database(self.boards.path(board_id), snapshot)
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                archive.write(snapshot, "board.sqlite")
        finally:
            if snapshot.exists():
                snapshot.unlink()
        return buffer.getvalue()

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
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
                raise ValidationFailure(
                    "Unsupported board archive format",
                    details={"supported": EXPORT_FORMAT_VERSION},
                )
            board_bytes = archive.read("board.sqlite")

        new_id = str(uuid4())
        name = str(manifest.get("board", {}).get("name") or "Imported board")[:200]
        description = str(manifest.get("board", {}).get("description") or "")[:20_000]
        self.registry.insert_board(new_id, name, description, "maintenance", BOARD_SCHEMA_VERSION)
        try:
            destination = self.boards.path(new_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(board_bytes)
            with self.boards.reader(new_id) as conn:
                quick_check = conn.exec_driver_sql("PRAGMA quick_check").scalar_one()
                if quick_check != "ok":
                    raise ValidationFailure(
                        "Imported database failed integrity check", details={"result": quick_check}
                    )
            if self.migrations is not None:
                migration = self.migrations.migrate_board(new_id)
                if migration.status == "failed":
                    raise ValidationFailure(
                        "Imported board could not be migrated to the current schema",
                        details={"status": "migration_failed"},
                    )
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

    def default_position(self, board_id: str) -> int:
        with self.boards.reader(board_id) as conn:
            return position_for_index(conn, "lists", "archived_at IS NULL", {}, None)
