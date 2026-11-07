"""A person's notes on a Ticket, addressed through the Loop that owns it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...schemas.card_notes import CardNoteCreate, CardNoteOut, CardNoteUpdate
from ...schemas.envelope import Envelope, OpenObject
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["cards"])

NOTES = "/boards/{board_id}/loops/{loop_id}/cards/{card_id}/notes"


@router.get(NOTES, response_model=Envelope[list[CardNoteOut]])
def list_card_notes(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """The Ticket's notes, oldest first."""
    notes = ctx.services.card_note.list(ctx.actor, board_id, loop_id, card_id)
    return ok(request, notes)


@router.post(NOTES, response_model=Envelope[CardNoteOut], status_code=201)
def add_card_note(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: CardNoteCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """A person's note (403 human_action_required for a token)."""
    note = ctx.services.card_note.add(ctx.actor, board_id, loop_id, card_id, payload)
    return ok(request, note)


@router.patch(f"{NOTES}/{{note_id}}", response_model=Envelope[CardNoteOut])
def edit_card_note(
    board_id: str,
    loop_id: str,
    card_id: str,
    note_id: str,
    payload: CardNoteUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """The author's edit of the version it read (403 note_author_only, 409 version_conflict)."""
    note = ctx.services.card_note.edit(ctx.actor, board_id, loop_id, card_id, note_id, payload)
    return ok(request, note)


@router.delete(f"{NOTES}/{{note_id}}", response_model=Envelope[OpenObject])
def delete_card_note(
    board_id: str,
    loop_id: str,
    card_id: str,
    note_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """The author deletes the note (403 note_author_only)."""
    ctx.services.card_note.delete(ctx.actor, board_id, loop_id, card_id, note_id)
    return ok(request, {"id": note_id, "deleted": True})
