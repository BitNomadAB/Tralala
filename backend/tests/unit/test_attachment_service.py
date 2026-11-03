"""AttachmentService on an in-memory board and a temporary directory: what an upload must be, where
its bytes go, the size limits, a Ticket's read-only Loop, download and soft deletion.

The service runs its real code; the repositories, the unit of work, the registry checks, the clock
and the id source are the typed fakes in ``tests/unit/fakes``, and the board's attachments directory
is a temporary directory.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.db.generated.board import AttachmentsRow
from app.repositories.board_files import AttachmentFiles
from app.services.attachments import (
    ALLOWED_TYPES,
    AttachmentEntry,
    AttachmentService,
    attachment_path,
)
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
WRITER = ActorContext(
    actor_id="person",
    actor_type="user",
    actor_name="Grace",
    scopes=frozenset({"cards:read", "cards:write"}),
    request_id="req-1",
)
READER = ActorContext(
    actor_id="reader", actor_type="user", actor_name="Reader", scopes=frozenset({"cards:read"})
)


@dataclass(frozen=True, slots=True)
class Directory:
    """Each board's attachments under ``root``."""

    root: Path

    def attachments_dir(self, board_id: str) -> Path:
        return self.root / board_id / "attachments"


def as_files(directory: Directory) -> AttachmentFiles:
    """The fake as the Protocol the service takes; pyright proves the contract."""
    return directory


class Ids:
    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    directory: Path
    service: AttachmentService

    def stored(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(path.name for path in self.directory.iterdir())

    def actions(self) -> list[tuple[str, str, str, dict[str, object]]]:
        return [
            (entry.action, entry.entity_type, entry.entity_id, json.loads(entry.changes_json))
            for entry in self.state.activity
        ]


def world(
    settings: Settings, tmp_path: Path, *, file_max: int = 64, board_max: int = 100
) -> World:
    state = BoardState()
    state.loops = {"open": loop_row("open"), "done": loop_row("done", completed_at=CREATED)}
    state.lists = {"todo": list_row("todo", "open", 1024)}
    state.cards = {
        "c1": card_row("c1", "todo", "open"),
        "c2": card_row("c2", "todo", "open"),
        "done-card": card_row("done-card", "todo", "done"),
    }
    limited = settings.model_copy(
        update={
            "attachment_max_bytes": file_max,
            "board_attachment_max_bytes": board_max,
            # No retry between two attempts, so a refused write fails at once on every host.
            "platform_profile": "posix",
        }
    )
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    service = AttachmentService(
        limited, checks, store, as_files(Directory(tmp_path)), clock=lambda: NOW, new_id=Ids()
    )
    return World(state, store, checks, tmp_path / BOARD_ID / "attachments", service)


def attachment(
    attachment_id: str,
    *,
    card_id: str | None = "c1",
    size: int = 10,
    created_at: str = CREATED,
    deleted_at: str | None = None,
) -> AttachmentsRow:
    return AttachmentsRow(
        id=attachment_id,
        card_id=card_id,
        discussion_id=None if card_id else "discussion-1",
        message_id=None,
        original_filename=f"{attachment_id}.txt",
        stored_filename=f"{attachment_id}.bin",
        content_type="text/plain",
        size_bytes=size,
        sha256="0" * 64,
        uploaded_by_actor_id="person",
        created_at=created_at,
        deleted_at=deleted_at,
    )


def upload(
    w: World,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    *,
    card_id: str = "c1",
    actor: ActorContext = WRITER,
) -> AttachmentEntry:
    return w.service.upload(
        actor, BOARD_ID, card_id=card_id, filename=filename, content_type=content_type, data=data
    )


# --- upload ---------------------------------------------------------------------------------------


def test_an_upload_stores_its_bytes_then_its_row_and_logs_it(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    entry = upload(w, "../Report (final).txt", b"hello", "text/plain; charset=utf-8")
    assert entry == {
        "id": "new-1",
        "card_id": "c1",
        "discussion_id": None,
        "message_id": None,
        "original_filename": "Report (final).txt",
        "stored_filename": "new-1.bin",
        "content_type": "text/plain",
        "size_bytes": 5,
        "sha256": hashlib.sha256(b"hello").hexdigest(),
        "uploaded_by_actor_id": "person",
        "created_at": STAMP,
        "deleted_at": None,
    }
    assert w.state.attachments["new-1"] == AttachmentsRow(**entry)
    assert w.stored() == ["new-1.bin"]
    assert (w.directory / "new-1.bin").read_bytes() == b"hello"
    assert w.actions() == [
        (
            "attachment.uploaded",
            "card",
            "c1",
            {"attachment_id": "new-1", "filename": "Report (final).txt", "size_bytes": 5},
        )
    ]
    (logged,) = w.state.activity
    assert (logged.id, logged.timestamp) == ("new-2", STAMP)
    assert w.checks.calls == [("ensure_active", BOARD_ID)]


def test_the_content_type_comes_from_the_extension_not_from_the_request(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    assert upload(w, "Shot.PNG", PNG, "application/octet-stream")["content_type"] == "image/png"
    assert upload(w, "notes.md", b"# t", "application/pdf")["content_type"] == "text/markdown"
    assert upload(w, "data.json", b"{}")["content_type"] == "application/json"


@pytest.mark.parametrize(
    ("filename", "data", "content_type", "message", "details"),
    [
        ("run.exe", b"MZ", None, "Unsupported file type", "allowed"),
        ("noext", b"x", None, "Unsupported file type", "allowed"),
        ("empty.txt", b"", None, "Uploaded file is empty", None),
        ("big.txt", b"x" * 65, None, "exceeds the configured size limit", "max_bytes"),
        ("fake.png", b"not a png", None, "does not match its extension", "extension"),
        ("bad.txt", b"\xff\xfe\xfa", None, "does not match its extension", "extension"),
        ("notes.txt", b"hi", " Image/PNG; x=1", "Content type does not match", None),
    ],
)
def test_an_upload_that_is_not_what_it_claims_is_refused_before_anything_is_written(
    settings: Settings,
    tmp_path: Path,
    filename: str,
    data: bytes,
    content_type: str | None,
    message: str,
    details: str | None,
) -> None:
    w = world(settings, tmp_path)
    with pytest.raises(ValidationFailure, match=message) as refused:
        upload(w, filename, data, content_type)
    if details is not None:
        assert refused.value.details is not None
        assert details in refused.value.details
    assert w.stored() == []
    assert w.state.attachments == {}
    assert w.store.commits + w.store.rollbacks == 0


def test_the_refusals_name_the_limits(settings: Settings, tmp_path: Path) -> None:
    w = world(settings, tmp_path)
    with pytest.raises(ValidationFailure) as refused:
        upload(w, "x.exe", b"x")
    assert refused.value.details == {"allowed": sorted(ALLOWED_TYPES)}
    with pytest.raises(ValidationFailure) as refused:
        upload(w, "big.txt", b"x" * 65)
    assert refused.value.details == {"max_bytes": 64}
    with pytest.raises(ValidationFailure) as refused:
        upload(w, "a.png", b"x")
    assert refused.value.details == {"extension": ".png"}


def test_an_upload_at_the_size_limit_is_accepted(settings: Settings, tmp_path: Path) -> None:
    w = world(settings, tmp_path)
    assert upload(w, "edge.txt", b"x" * 64)["size_bytes"] == 64


def test_an_image_may_declare_an_image_type(settings: Settings, tmp_path: Path) -> None:
    w = world(settings, tmp_path)
    assert upload(w, "a.png", PNG, "image/jpeg")["content_type"] == "image/png"


def test_an_upload_needs_the_card_scope_and_a_board_that_takes_writes(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    with pytest.raises(Forbidden):
        upload(w, "a.txt", b"a", actor=READER)
    w.checks.archived = frozenset({BOARD_ID})
    with pytest.raises(Conflict, match="archived"):
        upload(w, "a.txt", b"a")
    assert w.stored() == []


def test_an_upload_to_an_unknown_ticket_leaves_no_file_behind(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    with pytest.raises(NotFound, match="Card not found"):
        upload(w, "a.txt", b"a", card_id="nope")
    assert w.stored() == []
    assert w.state.attachments == {}
    assert w.store.rollbacks == 1


def test_an_upload_to_a_read_only_loop_leaves_no_file_behind(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    with pytest.raises(Conflict) as raised:
        upload(w, "a.txt", b"a", card_id="done-card")
    assert (raised.value.code, raised.value.details) == ("loop_read_only", {"card_id": "done-card"})
    assert w.stored() == []
    assert w.state.attachments == {}
    assert w.state.activity == []


def test_the_board_limit_counts_only_attachments_that_are_not_deleted(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {
        "kept": attachment("kept", size=60),
        "gone": attachment("gone", size=60, deleted_at=CREATED),
    }
    assert upload(w, "fits.txt", b"x" * 40)["size_bytes"] == 40
    with pytest.raises(ValidationFailure, match="Board attachment storage limit reached") as full:
        upload(w, "over.txt", b"x")
    assert full.value.details == {"board_max_bytes": 100}
    assert w.stored() == ["new-1.bin"]


def test_a_file_that_cannot_be_stored_leaves_nothing_behind(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    (w.directory / "new-1.bin").mkdir(parents=True)
    with pytest.raises(ValidationFailure, match="Could not store the uploaded file"):
        upload(w, "a.txt", b"a")
    assert w.stored() == ["new-1.bin"]
    assert w.state.attachments == {}
    assert w.store.commits + w.store.rollbacks == 0


# --- reads ----------------------------------------------------------------------------------------


def test_the_list_holds_the_attachments_that_are_not_deleted_oldest_first(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    rows = (
        attachment("late", created_at="2026-11-03T00:00:00Z"),
        attachment("tie-b", card_id="c2"),
        attachment("tie-a"),
        attachment("gone", deleted_at=CREATED),
        attachment("thread", card_id=None, created_at="2026-10-01T00:00:00Z"),
    )
    w.state.attachments = {row.id: row for row in rows}
    assert [entry["id"] for entry in w.service.list(BOARD_ID)] == [
        "thread",
        "tie-b",
        "tie-a",
        "late",
    ]
    assert [entry["id"] for entry in w.service.list(BOARD_ID, card_id="c1")] == ["tie-a", "late"]
    assert [entry["id"] for entry in w.service.list(BOARD_ID, card_id="")] == [
        "thread",
        "tie-b",
        "tie-a",
        "late",
    ]
    assert w.checks.calls == [("require_row", BOARD_ID)] * 3


def test_an_attachment_is_read_with_its_bytes(settings: Settings, tmp_path: Path) -> None:
    w = world(settings, tmp_path)
    upload(w, "a.txt", b"bytes")
    entry, data = w.service.read_bytes(BOARD_ID, "new-1")
    assert (entry["original_filename"], entry["content_type"], data) == (
        "a.txt",
        "text/plain",
        b"bytes",
    )
    assert w.service.get(BOARD_ID, "new-1") == entry


def test_a_deleted_or_unknown_attachment_or_a_missing_file_is_not_found(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {
        "gone": attachment("gone", deleted_at=CREATED),
        "lost": attachment("lost"),
    }
    for attachment_id in ("gone", "nope"):
        with pytest.raises(NotFound, match="Attachment not found"):
            w.service.get(BOARD_ID, attachment_id)
    with pytest.raises(NotFound, match="Attachment file is missing"):
        w.service.read_bytes(BOARD_ID, "lost")


# --- deletion -------------------------------------------------------------------------------------


def test_a_deleted_attachment_keeps_its_row_and_loses_its_file(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    upload(w, "a.txt", b"a")
    w.service.delete(WRITER, BOARD_ID, "new-1")
    assert w.state.attachments["new-1"].deleted_at == STAMP
    assert w.stored() == []
    assert w.actions()[1:] == [
        ("attachment.deleted", "card", "c1", {"attachment_id": "new-1", "filename": "a.txt"})
    ]
    with pytest.raises(NotFound, match="Attachment not found"):
        w.service.delete(WRITER, BOARD_ID, "new-1")


def test_deleting_an_attachment_whose_file_is_gone_still_deletes_it(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {"lost": attachment("lost")}
    w.service.delete(WRITER, BOARD_ID, "lost")
    assert w.state.attachments["lost"].deleted_at == STAMP


def test_an_attachment_outside_a_ticket_is_deleted_without_a_log(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {"thread": attachment("thread", card_id=None)}
    w.service.delete(WRITER, BOARD_ID, "thread")
    assert w.state.attachments["thread"].deleted_at == STAMP
    assert w.state.activity == []


def test_an_attachment_of_a_read_only_loop_is_not_deleted(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {"kept": attachment("kept", card_id="done-card")}
    w.directory.mkdir(parents=True)
    (w.directory / "kept.bin").write_bytes(b"k")
    with pytest.raises(Conflict) as raised:
        w.service.delete(WRITER, BOARD_ID, "kept")
    assert (raised.value.code, raised.value.details) == ("loop_read_only", {"card_id": "done-card"})
    assert w.state.attachments["kept"].deleted_at is None
    assert w.stored() == ["kept.bin"]


def test_deleting_needs_the_card_scope_and_a_board_that_takes_writes(
    settings: Settings, tmp_path: Path
) -> None:
    w = world(settings, tmp_path)
    w.state.attachments = {"a": attachment("a")}
    with pytest.raises(Forbidden):
        w.service.delete(READER, BOARD_ID, "a")
    w.checks.archived = frozenset({BOARD_ID})
    with pytest.raises(Conflict, match="archived"):
        w.service.delete(WRITER, BOARD_ID, "a")
    assert w.state.attachments["a"].deleted_at is None


# --- where the bytes are --------------------------------------------------------------------------


def test_a_stored_name_never_leaves_the_boards_directory(tmp_path: Path) -> None:
    files = as_files(Directory(tmp_path))
    path = attachment_path(files, BOARD_ID, "../../escape.bin")
    assert path == tmp_path / BOARD_ID / "attachments" / "escape.bin"
    assert path.parent.is_dir()
