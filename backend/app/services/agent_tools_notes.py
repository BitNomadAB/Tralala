"""The worker tools for a Loop's notes: ``write_note`` and ``read_notes``.

A note is what belongs to the Loop and to no single Ticket: the baseline a worker started from, the
gates that passed, a merge or a deploy, what is still open. Both handlers are typed on
``NoteKeeping``, the one attribute of the composition root they use, so a unit test runs them with
the real service on the typed fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..core.context import ActorContext
from .agent_tools_read import ToolArguments, ToolResult, _require, _text, _whole_number

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .loop_notes import LoopNoteService

# The page a worker reads unless it asks for another size.
NOTES_DEFAULT = 50
NOTES_LIMIT = 200


class NoteKeeping(Protocol):
    """What ``write_note`` and ``read_notes`` use of the composition root."""

    @property
    def loop_notes(self) -> LoopNoteService: ...


def write_note(services: NoteKeeping, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("loops:write")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    content = _require(args, "content")
    note, deduplicated = services.loop_notes.add(actor, board_id, loop_id, content)
    answer: ToolResult = {"note": note}
    if deduplicated:
        answer["deduplicated"] = True
    return answer


def read_notes(services: NoteKeeping, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("loops:read")
    board_id = _require(args, "board_id")
    loop_id = _require(args, "loop_id")
    limit = _whole_number(args, "limit", default=NOTES_DEFAULT, maximum=NOTES_LIMIT)
    page = services.loop_notes.list(
        actor, board_id, loop_id, limit=limit, before=_text(args.get("before"))
    )
    notes = page["notes"]
    return {
        "notes": notes,
        "count": page["count"],
        # A full page may have older notes behind it: pass this as before to read them.
        "older": notes[0]["id"] if notes and len(notes) == limit else None,
    }


__all__ = ["NOTES_DEFAULT", "NOTES_LIMIT", "NoteKeeping", "read_notes", "write_note"]
