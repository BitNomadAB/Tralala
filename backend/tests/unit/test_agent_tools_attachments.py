"""``list_attachments``, ``read_attachment`` and ``read_ticket``'s files on the fakes: the real
AttachmentService on an in-memory board and a file store over a temporary directory holding a text
file, a binary file and a text file whose bytes are not UTF-8, handed to the tools as the attribute
``AttachmentReading`` declares; then what ``tools/list`` and ``/llms.txt`` say about them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeIs

import pytest

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.db.generated.board import AttachmentsRow
from app.repositories.board_files import AttachmentFiles
from app.services.agent_tools import (
    ToolResult,
    list_attachments,
    read_attachment,
    tool_catalog,
)
from app.services.agent_tools_documents import PAGE_CHARS
from app.services.agent_tools_read import TICKET_ATTACHMENTS, ticket_attachments
from app.services.attachments import AttachmentService, attachment_entry
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)

READER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Reader",
    scopes=frozenset({"cards:read"}),
)
NOTES = "# Specification\n\nThe login page takes an email.\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
NOT_UTF8 = b"caf\xe9 au lait\n"
DOWNLOAD = f"/api/v1/boards/{BOARD_ID}/attachments/image/download"


@dataclass(frozen=True, slots=True)
class Directory:
    """Each board's attachments under ``root``."""

    root: Path

    def attachments_dir(self, board_id: str) -> Path:
        return self.root / board_id / "attachments"


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def as_files(directory: Directory) -> AttachmentFiles:
    """The fake as the Protocol the service takes; pyright proves the contract."""
    return directory


@dataclass(frozen=True, slots=True)
class AttachmentWorld:
    """What both tools declare they use of the composition root, and the board and its files."""

    attachment: AttachmentService
    state: BoardState
    directory: Path

    def store(self, row: AttachmentsRow, data: bytes) -> None:
        self.state.attachments[row.id] = row
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / row.stored_filename).write_bytes(data)


def stored(
    attachment_id: str,
    filename: str,
    content_type: str,
    *,
    size: int,
    created_at: str,
    card_id: str | None = "c1",
    deleted_at: str | None = None,
) -> AttachmentsRow:
    return AttachmentsRow(
        id=attachment_id,
        card_id=card_id,
        discussion_id=None if card_id else "discussion-1",
        message_id=None,
        original_filename=filename,
        stored_filename=f"{attachment_id}.bin",
        content_type=content_type,
        size_bytes=size,
        sha256="0" * 64,
        uploaded_by_actor_id="person",
        created_at=created_at,
        deleted_at=deleted_at,
    )


def attachment_world(settings: Settings, tmp_path: Path) -> AttachmentWorld:
    """Ticket ``c1`` holds, oldest first, ``notes`` (Markdown), ``image`` (a PNG), ``broken``
    (a .txt whose bytes are not UTF-8) and a deleted ``gone``; ``c2`` holds nothing."""
    state = BoardState()
    state.loops = {"open": loop_row("open")}
    state.lists = {"todo": list_row("todo", "open", 1024)}
    state.cards = {"c1": card_row("c1", "todo", "open"), "c2": card_row("c2", "todo", "open")}
    service = AttachmentService(
        settings, FakeBoardChecks(), FakeBoardUnitOfWork(state), as_files(Directory(tmp_path))
    )
    world = AttachmentWorld(service, state, tmp_path / BOARD_ID / "attachments")
    world.store(
        stored(
            "notes",
            "spec.md",
            "text/markdown",
            size=len(NOTES),
            created_at="2026-11-01T09:00:00Z",
        ),
        NOTES.encode(),
    )
    world.store(
        stored(
            "image", "screen.png", "image/png", size=len(PNG), created_at="2026-11-02T09:00:00Z"
        ),
        PNG,
    )
    world.store(
        stored(
            "broken",
            "log.txt",
            "text/plain",
            size=len(NOT_UTF8),
            created_at="2026-11-03T09:00:00Z",
        ),
        NOT_UTF8,
    )
    world.store(
        stored(
            "gone",
            "old.txt",
            "text/plain",
            size=3,
            created_at="2026-11-04T09:00:00Z",
            deleted_at="2026-11-05T09:00:00Z",
        ),
        b"old",
    )
    return world


def test_list_attachments_names_a_tickets_live_files_newest_first(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    answer = list_attachments(world, READER, {"board_id": BOARD_ID, "card_id": "c1"})
    assert answer["attachments"] == [
        {
            "id": "broken",
            "filename": "log.txt",
            "content_type": "text/plain",
            "size_bytes": len(NOT_UTF8),
            "uploaded_at": "2026-11-03T09:00:00Z",
            "text": True,
        },
        {
            "id": "image",
            "filename": "screen.png",
            "content_type": "image/png",
            "size_bytes": len(PNG),
            "uploaded_at": "2026-11-02T09:00:00Z",
            "text": False,
        },
        {
            "id": "notes",
            "filename": "spec.md",
            "content_type": "text/markdown",
            "size_bytes": len(NOTES),
            "uploaded_at": "2026-11-01T09:00:00Z",
            "text": True,
        },
    ]
    assert answer["count"] == 3
    step = str(answer["next_step"])
    assert "read_attachment" in step
    assert f"/api/v1/boards/{BOARD_ID}/attachments/{{id}}/download" in step


def test_list_attachments_says_so_when_a_ticket_has_none_and_refuses_an_unknown_one(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    empty = list_attachments(world, READER, {"board_id": BOARD_ID, "card_id": "c2"})
    assert (empty["attachments"], empty["count"]) == ([], 0)
    assert empty["next_step"] == "This Ticket has no attachments."
    with pytest.raises(NotFound, match="Ticket not found"):
        list_attachments(world, READER, {"board_id": BOARD_ID, "card_id": "nope"})
    with pytest.raises(ValidationFailure, match="card_id is required"):
        list_attachments(world, READER, {"board_id": BOARD_ID})


def test_both_tools_need_cards_read(settings: Settings, tmp_path: Path) -> None:
    world = attachment_world(settings, tmp_path)
    stranger = ActorContext(
        actor_id="agent-9", actor_type="agent", actor_name="Stranger", scopes=frozenset()
    )
    with pytest.raises(Forbidden):
        list_attachments(world, stranger, {"board_id": BOARD_ID, "card_id": "c1"})
    with pytest.raises(Forbidden):
        read_attachment(world, stranger, {"board_id": BOARD_ID, "attachment_id": "notes"})


def test_read_attachment_answers_a_text_file_as_numbered_lines(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    answer = read_attachment(world, READER, {"board_id": BOARD_ID, "attachment_id": "notes"})
    assert answer == {
        "attachment": {
            "id": "notes",
            "filename": "spec.md",
            "content_type": "text/markdown",
            "size_bytes": len(NOTES),
            "uploaded_at": "2026-11-01T09:00:00Z",
            "text": True,
        },
        "card_id": "c1",
        "lines": "1-3 of 3",
        "text": "1\t# Specification\n2\t\n3\tThe login page takes an email.",
        "continue_from": None,
        "next_step": "That is the whole file.",
    }


def test_read_attachment_pages_a_long_text_file_as_read_document_does(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    line = "x" * 99
    content = "\ufeff" + "\n".join(line for _ in range(1000))  # 100 000 characters and a BOM
    world.store(
        stored(
            "long",
            "trace.json",
            "application/json",
            size=len(content),
            created_at="2026-11-06T09:00:00Z",
        ),
        content.encode(),
    )
    first = read_attachment(world, READER, {"board_id": BOARD_ID, "attachment_id": "long"})
    assert isinstance(first["text"], str)
    assert len(first["text"]) <= PAGE_CHARS
    assert first["text"].startswith("1\tx")  # the byte-order mark is dropped, as the upload read it
    rest = first["continue_from"]
    assert isinstance(rest, int)
    assert first["lines"] == f"1-{rest - 1} of 1000"
    assert first["next_step"] == f"Call read_attachment again with start_line {rest} for the rest."
    second = read_attachment(
        world, READER, {"board_id": BOARD_ID, "attachment_id": "long", "start_line": rest}
    )
    assert second["lines"] == f"{rest}-1000 of 1000"
    assert second["continue_from"] is None
    with pytest.raises(ValidationFailure, match="past the end"):
        read_attachment(
            world, READER, {"board_id": BOARD_ID, "attachment_id": "long", "start_line": 1001}
        )


def test_read_attachment_never_answers_a_binary_files_content(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    # Its bytes are not even read: the answer stands with the file gone from the store.
    (world.directory / "image.bin").unlink()
    answer = read_attachment(world, READER, {"board_id": BOARD_ID, "attachment_id": "image"})
    assert answer == {
        "attachment": {
            "id": "image",
            "filename": "screen.png",
            "content_type": "image/png",
            "size_bytes": len(PNG),
            "uploaded_at": "2026-11-02T09:00:00Z",
            "text": False,
        },
        "card_id": "c1",
        "download": DOWNLOAD,
        "next_step": (
            "screen.png is not text, so no tool answers its content: fetch its bytes over "
            f"GET {DOWNLOAD} with the same key."
        ),
    }


def test_read_attachment_refuses_bytes_that_are_not_utf8_naming_the_file(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    with pytest.raises(ValidationFailure, match=r"log\.txt is not valid UTF-8 text") as refused:
        read_attachment(world, READER, {"board_id": BOARD_ID, "attachment_id": "broken"})
    assert refused.value.code == "attachment_not_text"
    assert refused.value.status_code == 422
    assert refused.value.details == {
        "attachment_id": "broken",
        "filename": "log.txt",
        "byte_offset": 3,
    }


def test_read_attachment_refuses_a_deleted_or_unknown_file(
    settings: Settings, tmp_path: Path
) -> None:
    world = attachment_world(settings, tmp_path)
    for attachment_id in ("gone", "nope"):
        with pytest.raises(NotFound, match="Attachment not found"):
            read_attachment(world, READER, {"board_id": BOARD_ID, "attachment_id": attachment_id})


def test_the_service_reads_only_a_text_type_as_text(settings: Settings, tmp_path: Path) -> None:
    world = attachment_world(settings, tmp_path)
    with pytest.raises(ValidationFailure, match="not a text file") as refused:
        world.attachment.read_text(BOARD_ID, "image")
    assert refused.value.code == "attachment_not_text"
    entry, content = world.attachment.read_text(BOARD_ID, "notes")
    assert (entry["id"], content) == ("notes", NOTES)


def test_read_ticket_names_the_newest_fifty_files_and_counts_them_all() -> None:
    entries = [
        attachment_entry(
            stored(
                f"file-{number:02}",
                f"file-{number:02}.txt",
                "text/plain",
                size=1,
                created_at=f"2026-11-01T09:{number:02}:00Z",
            )
        )
        for number in reversed(range(TICKET_ATTACHMENTS + 3))
    ]
    shown = ticket_attachments(entries)
    rows = shown["attachments"]
    assert _is_list(rows)
    assert len(rows) == TICKET_ATTACHMENTS == 50
    assert rows[0] == {
        "id": "file-52",
        "filename": "file-52.txt",
        "content_type": "text/plain",
        "size_bytes": 1,
        "uploaded_at": "2026-11-01T09:52:00Z",
        "text": True,
    }
    assert shown["attachment_count"] == 53
    assert ticket_attachments([]) == {"attachments": [], "attachment_count": 0}


def test_tools_list_and_llms_txt_describe_the_two_tools(settings: Settings) -> None:
    catalogue = tool_catalog()
    for name in ("list_attachments", "read_attachment"):
        assert catalogue[name].scopes == ("cards:read",)
    listed = [tool["name"] for tool in tool_list(READER)]
    assert listed.index("read_ticket") < listed.index("list_attachments")
    assert listed.index("list_attachments") < listed.index("read_attachment")
    text = render_bootstrap(settings)
    assert "### list_attachments (requires `cards:read`)" in text
    assert "### read_attachment (requires `cards:read`)" in text
    section = text.split("## 3.")[1].split("## 4.")[0]
    assert section.index("`read_ticket`") < section.index("`read_attachment`")
    assert "`list_attachments`" in section
    schema: ToolResult = dict(catalogue["read_attachment"].input_schema)
    assert schema["required"] == ["board_id", "attachment_id"]
