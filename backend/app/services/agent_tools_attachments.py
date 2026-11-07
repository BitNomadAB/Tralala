"""``list_attachments`` and ``read_attachment``: the files a person attached to a Ticket, as a
worker reads them.

A row is what a file is (its id, filename, content type, size, when it was uploaded) and whether
it is text: a ``.txt``, ``.md`` or ``.json`` file ``read_attachment`` answers as numbered lines, a
page at a time by the same rule as ``read_document`` (``start_line``, ``lines``, ``text``,
``continue_from``, at most ``PAGE_CHARS`` characters a page). Every other file (an image, a PDF, an
Office document) is never a tool answer: ``read_attachment`` gives its metadata and the REST route
that downloads its bytes with the same key, and no answer carries base64. The bytes are read by
``AttachmentService`` through its file store, never here. Writing a file from a worker is not a
tool.

The handlers are public and typed on the attribute of the composition root they use, so a unit
test runs them with the real service on the typed fakes. Their catalogue entries are built here
too (``attachment_tools``) and placed by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..core.context import ActorContext
from .agent_tools_documents import MAX_START_LINE, PAGE_CHARS, text_page
from .agent_tools_read import ToolArguments, ToolResult, _require, _whole_number
from .agent_tools_schema import AgentTool, ArgumentSchema, object_schema, string_argument
from .attachments import attachment_summary, is_text

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .attachments import AttachmentService


class AttachmentReading(Protocol):
    """What ``list_attachments`` and ``read_attachment`` use of the composition root."""

    @property
    def attachment(self) -> AttachmentService: ...


def download_path(board_id: str, attachment_id: str) -> str:
    """The REST route that answers a file's bytes, for the same key."""
    return f"/api/v1/boards/{board_id}/attachments/{attachment_id}/download"


def list_attachments(
    services: AttachmentReading, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:read")
    board_id = _require(args, "board_id")
    card_id = _require(args, "card_id")
    rows = [
        attachment_summary(entry) for entry in services.attachment.for_ticket(board_id, card_id)
    ]
    return {
        "board_id": board_id,
        "card_id": card_id,
        "attachments": rows,
        "count": len(rows),
        "next_step": (
            "This Ticket has no attachments."
            if not rows
            else (
                "Read a file whose text is true with read_attachment; any other file is fetched "
                f"over GET {download_path(board_id, '{id}')} with the same key."
            )
        ),
    }


def read_attachment(
    services: AttachmentReading, actor: ActorContext, args: ToolArguments
) -> ToolResult:
    actor.require("cards:read")
    board_id = _require(args, "board_id")
    attachment_id = _require(args, "attachment_id")
    entry = services.attachment.get(board_id, attachment_id)
    answer: ToolResult = {"attachment": attachment_summary(entry), "card_id": entry["card_id"]}
    if not is_text(entry):
        download = download_path(board_id, entry["id"])
        return answer | {
            "download": download,
            "next_step": (
                f"{entry['original_filename']} is not text, so no tool answers its content: "
                f"fetch its bytes over GET {download} with the same key."
            ),
        }
    start = _whole_number(args, "start_line", default=1, maximum=MAX_START_LINE)
    _, content = services.attachment.read_text(board_id, entry["id"])
    page = text_page(content, start)
    rest = page["continue_from"]
    return (
        answer
        | page
        | {
            "next_step": (
                "That is the whole file."
                if rest is None
                else f"Call read_attachment again with start_line {rest} for the rest."
            )
        }
    )


def attachment_tools(board_id: ArgumentSchema, card_id: ArgumentSchema) -> list[AgentTool]:
    """The catalogue entries of a Ticket's files: the list, and reading one."""
    return [
        AgentTool(
            name="list_attachments",
            description=(
                "List the files attached to one Ticket, newest first: id, filename, content "
                "type, size, when it was uploaded and text (true for .txt, .md and .json, which "
                "read_attachment answers as text). read_ticket carries the newest 50."
            ),
            scopes=("cards:read",),
            input_schema=object_schema(
                {"board_id": board_id, "card_id": card_id}, required=["board_id", "card_id"]
            ),
            handler=list_attachments,
        ),
        AgentTool(
            name="read_attachment",
            description=(
                "Read one attached file. A text file (.txt, .md, .json) answers as numbered lines, "
                f"at most {PAGE_CHARS} characters, with continue_from for the rest, as "
                "read_document does; one that is not valid UTF-8 is refused "
                "(attachment_not_text). Any other file answers its metadata and the REST route "
                "that downloads its bytes with the same key, never its content."
            ),
            scopes=("cards:read",),
            input_schema=object_schema(
                {
                    "board_id": board_id,
                    "attachment_id": string_argument(
                        "Attachment identifier from read_ticket or list_attachments"
                    ),
                    "start_line": {"type": "number", "minimum": 1},
                },
                required=["board_id", "attachment_id"],
            ),
            handler=read_attachment,
        ),
    ]


__all__ = [
    "AttachmentReading",
    "attachment_tools",
    "download_path",
    "list_attachments",
    "read_attachment",
]
