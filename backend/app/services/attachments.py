"""Ticket attachments: validated upload, authenticated download and soft deletion.

Bytes live outside the database (``data/boards/{uuid}/attachments/{uuid}``) while metadata lives in
the board database. Original filenames are preserved for display only; paths are never derived from
user input.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import NotFound, ValidationFailure
from ..core.platform import remove_file, replace_file
from ..storage.board_db import BoardDatabaseManager
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import require_mutable_card

# extension -> (content type, magic-byte predicate name)
ALLOWED_TYPES: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}

TEXT_TYPES = {".txt", ".md", ".json"}
ZIP_TYPES = {".docx", ".pptx", ".xlsx"}
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._ ()\[\]-]+")


def sanitize_filename(raw: str | None) -> str:
    name = Path(str(raw or "")).name.strip()
    name = _FILENAME_SAFE.sub("_", name)
    name = name.lstrip(".") or "attachment"
    return name[:200]


def sniff_matches(extension: str, data: bytes) -> bool:
    if extension in TEXT_TYPES:
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        return True
    if extension in ZIP_TYPES:
        return data.startswith(b"PK\x03\x04")
    if extension == ".pdf":
        return data.startswith(b"%PDF")
    if extension in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if extension == ".ppt":
        return data.startswith(b"\xd0\xcf\x11\xe0")
    return False


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


class AttachmentService:
    def __init__(self, board_service: BoardService, *, boards: BoardDatabaseManager) -> None:
        self.board_service = board_service
        self.boards = boards
        self.settings = board_service.settings

    # --- storage -------------------------------------------------------------

    def directory(self, board_id: str) -> Path:
        path = self.boards.attachments_dir(board_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def file_path(self, board_id: str, stored_filename: str) -> Path:
        return self.directory(board_id) / sanitize_filename(stored_filename)

    def _board_usage(self, conn: Any) -> int:
        value = conn.execute(
            text("SELECT COALESCE(SUM(size_bytes), 0) FROM attachments WHERE deleted_at IS NULL")
        ).scalar_one()
        return int(value)

    # --- queries -------------------------------------------------------------

    def list(self, board_id: str, *, card_id: str | None = None) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            if card_id:
                return _rows(
                    conn,
                    "SELECT * FROM attachments WHERE deleted_at IS NULL AND card_id = :card_id"
                    " ORDER BY created_at",
                    {"card_id": card_id},
                )
            return _rows(
                conn,
                "SELECT * FROM attachments WHERE deleted_at IS NULL ORDER BY created_at",
                {},
            )

    def _row(self, conn: Any, attachment_id: str) -> dict[str, Any]:
        row = conn.execute(
            text("SELECT * FROM attachments WHERE id = :id AND deleted_at IS NULL"),
            {"id": attachment_id},
        ).mappings().first()
        if row is None:
            raise NotFound("Attachment not found")
        return dict(row)

    def get(self, board_id: str, attachment_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            return self._row(conn, attachment_id)

    def read_bytes(self, board_id: str, attachment_id: str) -> tuple[dict[str, Any], bytes]:
        row = self.get(board_id, attachment_id)
        path = self.file_path(board_id, row["stored_filename"])
        if not path.exists():
            raise NotFound("Attachment file is missing")
        return row, path.read_bytes()

    # --- commands ------------------------------------------------------------

    def upload(
        self,
        actor: ActorContext,
        board_id: str,
        *,
        card_id: str,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> dict[str, Any]:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        name = sanitize_filename(filename)
        extension = Path(name).suffix.lower()
        if extension not in ALLOWED_TYPES:
            raise ValidationFailure(
                "Unsupported file type",
                details={"allowed": sorted(ALLOWED_TYPES)},
            )
        if not data:
            raise ValidationFailure("Uploaded file is empty")
        if len(data) > self.settings.attachment_max_bytes:
            raise ValidationFailure(
                "File exceeds the configured size limit",
                details={"max_bytes": self.settings.attachment_max_bytes},
            )
        if not sniff_matches(extension, data):
            raise ValidationFailure(
                "File content does not match its extension",
                details={"extension": extension},
            )
        declared = (content_type or "").split(";")[0].strip().lower()
        if declared.startswith("image/") and not ALLOWED_TYPES[extension].startswith("image/"):
            raise ValidationFailure("Content type does not match the file extension")
        attachment_id = str(uuid4())
        stored = f"{attachment_id}.bin"
        now = utcnow()
        # The file lands on disk before the row names it: a crash then leaves an unreferenced file
        # (invisible, prunable) instead of a row whose attachment can never be downloaded.
        target = self.file_path(board_id, stored)
        staging = target.with_name(f".{attachment_id}.uploading")
        profile = self.settings.file_profile
        try:
            staging.write_bytes(data)
            replace_file(staging, target, profile=profile)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise ValidationFailure("Could not store the uploaded file") from exc
        try:
            return self._insert_upload(
                actor, board_id, attachment_id, stored, name, extension, data, now, card_id
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def _insert_upload(
        self,
        actor: ActorContext,
        board_id: str,
        attachment_id: str,
        stored: str,
        name: str,
        extension: str,
        data: bytes,
        now: str,
        card_id: str,
    ) -> dict[str, Any]:
        with self.boards.session(board_id) as conn:
            card = conn.execute(
                text("SELECT id FROM cards WHERE id = :id"), {"id": card_id}
            ).first()
            if card is None:
                raise NotFound("Card not found")
            require_mutable_card(conn, card_id)
            usage = self._board_usage(conn)
            if usage + len(data) > self.settings.board_attachment_max_bytes:
                raise ValidationFailure(
                    "Board attachment storage limit reached",
                    details={"board_max_bytes": self.settings.board_attachment_max_bytes},
                )
            conn.execute(
                text(
                    "INSERT INTO attachments"
                    " (id, card_id, discussion_id, message_id, original_filename,"
                    "  stored_filename, content_type, size_bytes, sha256, uploaded_by_actor_id,"
                    "  created_at, deleted_at)"
                    " VALUES (:id, :card_id, NULL, NULL, :name, :stored, :content_type, :size,"
                    "         :sha, :actor_id, :now, NULL)"
                ),
                {
                    "id": attachment_id,
                    "card_id": card_id,
                    "name": name,
                    "stored": stored,
                    "content_type": ALLOWED_TYPES[extension],
                    "size": len(data),
                    "sha": hashlib.sha256(data).hexdigest(),
                    "actor_id": actor.actor_id,
                    "now": now,
                },
            )
            log_activity(
                conn,
                actor,
                action="attachment.uploaded",
                entity_type="card",
                entity_id=card_id,
                changes={
                    "attachment_id": attachment_id,
                    "filename": name,
                    "size_bytes": len(data),
                },
            )
        return self.get(board_id, attachment_id)

    def delete(self, actor: ActorContext, board_id: str, attachment_id: str) -> None:
        actor.require("cards:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            row = self._row(conn, attachment_id)
            if row.get("card_id"):
                require_mutable_card(conn, row["card_id"])
            conn.execute(
                text("UPDATE attachments SET deleted_at = :now WHERE id = :id"),
                {"now": utcnow(), "id": attachment_id},
            )
            if row.get("card_id"):
                log_activity(
                    conn,
                    actor,
                    action="attachment.deleted",
                    entity_type="card",
                    entity_id=row["card_id"],
                    changes={"attachment_id": attachment_id, "filename": row["original_filename"]},
                )
        path = self.file_path(board_id, row["stored_filename"])
        if path.exists():
            remove_file(path, profile=self.settings.file_profile)
