"""A Loop's notes: the append-only log a person or a worker writes on the Loop."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.loops import NoteOut, NotePageOut, NoteWrite
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["loops"])


@router.get("/boards/{board_id}/loops/{loop_id}/notes", response_model=Envelope[NotePageOut])
def list_notes(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, object]:
    page = ctx.services.loop_notes.list(ctx.actor, board_id, loop_id, limit=limit, before=before)
    return ok(request, page)


@router.post(
    "/boards/{board_id}/loops/{loop_id}/notes",
    response_model=Envelope[NoteOut],
    status_code=201,
)
def add_note(
    board_id: str,
    loop_id: str,
    payload: NoteWrite,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    note, deduplicated = ctx.services.loop_notes.add(ctx.actor, board_id, loop_id, payload.content)
    return ok(request, {**note, "deduplicated": deduplicated})
