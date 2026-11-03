"""Export and import of a board archive: its database, its uploaded files and a manifest.

An archive is a zip of ``manifest.json``, ``board.sqlite`` and ``attachments/``. An import is judged
before anything opens it, migrated to the schema head before the board takes requests, and taken
away in full when any step fails. ``BoardService`` (``services.boards``) delegates here with its
settings, registry and board units of work, board files, migrator, schema head, clock and id
source, and re-exports the constants.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import JsonValue

from ..core.config import Settings
from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..core.platform import copy_file, remove_file, remove_tree, retry_io
from ..db.generated.registry import BoardsRow
from ..repositories.board import BoardUnitOfWork
from ..repositories.board_files import BoardFiles, BoardMigrator, ProblemReason
from ..repositories.registry import RegistryUnitOfWork
from . import boards_registry
from .boards_registry import BoardSchema, json_object
from .common import archive_file_name

logger = logging.getLogger("tralala")

MANIFEST_MAX_BYTES = 1024 * 1024
EXPORT_FORMAT_VERSION = 2
MAX_ARCHIVE_ATTACHMENTS = 1000

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


def export_archive(
    files: BoardFiles,
    settings: Settings,
    board_id: str,
    row: BoardsRow,
    *,
    now: Callable[[], str],
) -> bytes:
    """The board's database, its uploaded files and a manifest, as one zip."""
    attachments = attachment_files(files, board_id)
    manifest = {
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": now(),
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
    snapshot = files.path(board_id).with_suffix(".export.sqlite")
    profile = settings.file_profile
    try:
        files.snapshot(board_id, snapshot)
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


def copy_attachments(
    board_files: BoardFiles, settings: Settings, source_board_id: str, target_board_id: str
) -> int:
    """A duplicated board keeps its uploaded files, or every attachment row points nowhere."""
    files = attachment_files(board_files, source_board_id)
    if not files:
        return 0
    directory = board_files.attachments_dir(target_board_id)
    directory.mkdir(parents=True, exist_ok=True)
    profile = settings.file_profile
    for file in files:
        copy_file(file, directory / file.name, profile=profile)
    return len(files)


def attachment_files(files: BoardFiles, board_id: str) -> list[Path]:
    directory = files.attachments_dir(board_id)
    if not directory.exists():
        return []
    return sorted(file for file in directory.glob("*") if file.is_file())


def import_archive(
    actor: ActorContext,
    data: bytes,
    *,
    settings: Settings,
    store: RegistryUnitOfWork,
    boards: BoardUnitOfWork,
    files: BoardFiles,
    migrations: BoardMigrator,
    schema: BoardSchema,
    now: Callable[[], str],
    new_id: Callable[[], str],
) -> str:
    """The id of the board an archive became; a refused or failed import leaves nothing behind."""
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
        manifest = json_object(
            json.loads(_archive_member(archive, "manifest.json", MANIFEST_MAX_BYTES)),
            "the manifest",
        )
        if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
            raise ValidationFailure(
                "Unsupported board archive format",
                details={"supported": EXPORT_FORMAT_VERSION},
            )
        board_bytes = _archive_member(archive, "board.sqlite", int(settings.board_import_max_bytes))
        attachment_entries = [
            entry
            for entry in archive.namelist()
            if entry.startswith("attachments/") and not entry.endswith("/")
        ]
        declared_files = json_object(
            manifest.get("attachments") or {}, "the manifest's attachments"
        )
        declared = _as_int(declared_files.get("bytes") or 0)
        limit = int(settings.board_attachment_max_bytes)
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

    board_id = new_id()
    board = json_object(manifest.get("board", {}), "the manifest's board")
    name = str(board.get("name") or "Imported board")[:200]
    description = str(board.get("description") or "")[:20_000]
    try:
        _accept_import(
            actor,
            board_id,
            name=name,
            description=description,
            database=board_bytes,
            attachments=attachments,
            store=store,
            boards=boards,
            files=files,
            migrations=migrations,
            schema=schema,
            now=now,
            new_id=new_id,
        )
    except Exception:
        _discard_import(store, files, settings, board_id, now=now)
        raise
    return board_id


def _accept_import(
    actor: ActorContext,
    board_id: str,
    *,
    name: str,
    description: str,
    database: bytes,
    attachments: list[tuple[str, bytes]],
    store: RegistryUnitOfWork,
    boards: BoardUnitOfWork,
    files: BoardFiles,
    migrations: BoardMigrator,
    schema: BoardSchema,
    now: Callable[[], str],
    new_id: Callable[[], str],
) -> None:
    destination = files.path(board_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(database)
    # Judged before anything opens it, and before it has a row: a file that is not a sound
    # board database is never listed, recovered, migrated or opened as a board.
    problem = migrations.check_imported(board_id)
    if problem is not None:
        raise _refused(problem.reason, problem.detail)
    if attachments:
        directory = files.attachments_dir(board_id)
        directory.mkdir(parents=True, exist_ok=True)
        for file_name, payload in attachments:
            (directory / file_name).write_bytes(payload)
    boards_registry.add_row(store, schema, board_id, name, description, now=now)
    # Migrated before it is opened: opening checks the revision, so an archive from an older
    # release is brought to the head first.
    if migrations.migrate_board(board_id).status == "failed":
        raise _refused("migration_failed", "the backend log names the cause")
    with boards.writer(board_id) as imported:
        imported.metadata.claim(board_id, now=now())
        changes = {"source_format": EXPORT_FORMAT_VERSION}
        boards_registry.log_activity(
            imported, actor, "board.imported", board_id, changes, new_id=new_id, now=now
        )
    boards_registry.activate(store, schema, board_id, now=now)


def _discard_import(
    store: RegistryUnitOfWork,
    files: BoardFiles,
    settings: Settings,
    board_id: str,
    *,
    now: Callable[[], str],
) -> None:
    """Take away what a refused or failed import wrote: its files and the pre-migration backup
    the Migration Manager may have taken, then its row. An import is all or nothing.

    Files go first, as in ``delete``: when the host will not let go of one, the row stays,
    marked ``error``, so the leftover is visible and can be deleted later.
    """
    profile = settings.file_profile
    with store.reader() as repos:
        registered = repos.boards.get(board_id) is not None
    try:
        with files.locked(board_id):
            files.delete_database(board_id)
            remove_tree(settings.backups_dir / board_id, profile=profile)
    except OSError as exc:
        logger.warning(
            "board_import_leftover",
            extra={
                "board_id": board_id,
                "leftover": f"boards/{board_id}",
                "reason": type(exc).__name__,
            },
        )
        if registered:
            boards_registry.update_row(store, board_id, {"status": "error"}, now=now)
        return
    if registered:
        with store.writer() as repos:
            repos.boards.delete(board_id)
