"""Ticket attachments: validated upload, authenticated download and soft deletion.

Bytes live outside the database (``data/boards/{uuid}/attachments/{uuid}``) while metadata lives in
the board database. Original filenames are preserved for display only; paths are never derived from
user input. The service reaches the metadata only through the board unit of work, the directory
only through ``AttachmentFiles`` and the board's registry row through ``BoardChecks``; a Ticket's
attachments follow its Loop (``ensure_ticket_writable``). The clock and the id source are passed in,
so every rule here runs in a unit test without a database.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import NotFound, ValidationFailure
from ..core.platform import remove_file, replace_file
from ..db.generated.board import AttachmentsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.board_files import AttachmentFiles
from .activity import activity_entry
from .lists import BoardChecks
from .loops import ensure_ticket_writable

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


class AttachmentEntry(TypedDict):
    """An attachment's row as the API returns it."""

    id: str
    card_id: str | None
    discussion_id: str | None
    message_id: str | None
    original_filename: str
    stored_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_actor_id: str
    created_at: str
    deleted_at: str | None


def attachment_entry(row: AttachmentsRow) -> AttachmentEntry:
    return {
        "id": row.id,
        "card_id": row.card_id,
        "discussion_id": row.discussion_id,
        "message_id": row.message_id,
        "original_filename": row.original_filename,
        "stored_filename": row.stored_filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "uploaded_by_actor_id": row.uploaded_by_actor_id,
        "created_at": row.created_at,
        "deleted_at": row.deleted_at,
    }


def attachment_path(files: AttachmentFiles, board_id: str, stored_filename: str) -> Path:
    """Where a stored file's bytes are: the board's attachments directory (created when it is
    missing) and the stored name, sanitized again so a row can never point outside it."""
    directory = files.attachments_dir(board_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / sanitize_filename(stored_filename)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class AttachmentService:
    def __init__(
        self,
        settings: Settings,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        files: AttachmentFiles,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.settings = settings
        self.boards = boards
        self.store = store
        self.files = files
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- storage -------------------------------------------------------------

    def file_path(self, board_id: str, stored_filename: str) -> Path:
        return attachment_path(self.files, board_id, stored_filename)

    @staticmethod
    def _live(repos: BoardRepositories, attachment_id: str) -> AttachmentsRow:
        row = repos.attachments.get_live(attachment_id)
        if row is None:
            raise NotFound("Attachment not found")
        return row

    # --- queries -------------------------------------------------------------

    def list(self, board_id: str, *, card_id: str | None = None) -> list[AttachmentEntry]:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            rows = repos.attachments.live(card_id=card_id or None)
        return [attachment_entry(row) for row in rows]

    def get(self, board_id: str, attachment_id: str) -> AttachmentEntry:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return attachment_entry(self._live(repos, attachment_id))

    def read_bytes(self, board_id: str, attachment_id: str) -> tuple[AttachmentEntry, bytes]:
        entry = self.get(board_id, attachment_id)
        path = self.file_path(board_id, entry["stored_filename"])
        if not path.exists():
            raise NotFound("Attachment file is missing")
        return entry, path.read_bytes()

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
    ) -> AttachmentEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
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
        attachment_id = self._new_id()
        row = AttachmentsRow(
            id=attachment_id,
            card_id=card_id,
            discussion_id=None,
            message_id=None,
            original_filename=name,
            stored_filename=f"{attachment_id}.bin",
            content_type=ALLOWED_TYPES[extension],
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by_actor_id=actor.actor_id,
            created_at=self._now(),
            deleted_at=None,
        )
        # The file lands on disk before the row names it: a crash then leaves an unreferenced file
        # (invisible, prunable) instead of a row whose attachment can never be downloaded.
        target = self.file_path(board_id, row.stored_filename)
        staging = target.with_name(f".{attachment_id}.uploading")
        profile = self.settings.file_profile
        try:
            staging.write_bytes(data)
            replace_file(staging, target, profile=profile)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise ValidationFailure("Could not store the uploaded file") from exc
        try:
            self._insert_upload(actor, board_id, card_id, row)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return attachment_entry(row)

    def _insert_upload(
        self, actor: ActorContext, board_id: str, card_id: str, row: AttachmentsRow
    ) -> None:
        with self.store.writer(board_id) as repos:
            if repos.cards.get(card_id) is None:
                raise NotFound("Card not found")
            ensure_ticket_writable(repos, card_id)
            usage = repos.attachments.live_size()
            if usage + row.size_bytes > self.settings.board_attachment_max_bytes:
                raise ValidationFailure(
                    "Board attachment storage limit reached",
                    details={"board_max_bytes": self.settings.board_attachment_max_bytes},
                )
            repos.attachments.add(row)
            repos.activity.add(
                activity_entry(
                    actor,
                    action="attachment.uploaded",
                    entity_type="card",
                    entity_id=card_id,
                    changes={
                        "attachment_id": row.id,
                        "filename": row.original_filename,
                        "size_bytes": row.size_bytes,
                    },
                    entry_id=self._new_id(),
                    timestamp=self._now(),
                )
            )

    def delete(self, actor: ActorContext, board_id: str, attachment_id: str) -> None:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            row = self._live(repos, attachment_id)
            if row.card_id:
                ensure_ticket_writable(repos, row.card_id)
            repos.attachments.mark_deleted(attachment_id, now=self._now())
            if row.card_id:
                repos.activity.add(
                    activity_entry(
                        actor,
                        action="attachment.deleted",
                        entity_type="card",
                        entity_id=row.card_id,
                        changes={"attachment_id": attachment_id, "filename": row.original_filename},
                        entry_id=self._new_id(),
                        timestamp=self._now(),
                    )
                )
        path = self.file_path(board_id, row.stored_filename)
        if path.exists():
            remove_file(path, profile=self.settings.file_profile)
