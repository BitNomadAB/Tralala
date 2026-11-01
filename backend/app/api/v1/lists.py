from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.lists import ListCreate, ListMove, ListOut, ListUpdate
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["lists"])


@router.get("/boards/{board_id}/lists", response_model=Envelope[list[ListOut]])
async def list_lists(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    include_archived: Annotated[bool, Query()] = False,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.list.list(board_id, include_archived=include_archived))


@router.post("/boards/{board_id}/lists", response_model=Envelope[ListOut], status_code=201)
async def create_list(
    board_id: str,
    payload: ListCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.list.create(ctx.actor, board_id, payload))


@router.get("/boards/{board_id}/lists/{list_id}", response_model=Envelope[ListOut])
async def get_list(
    board_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.list.get(board_id, list_id))


@router.patch("/boards/{board_id}/lists/{list_id}", response_model=Envelope[ListOut])
async def update_list(
    board_id: str,
    list_id: str,
    payload: ListUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.list.update(ctx.actor, board_id, list_id, payload))


@router.post("/boards/{board_id}/lists/{list_id}/move", response_model=Envelope[list[ListOut]])
async def move_list(
    board_id: str,
    list_id: str,
    payload: ListMove,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.list.move(ctx.actor, board_id, list_id, payload))


@router.post("/boards/{board_id}/lists/{list_id}/archive", response_model=Envelope[ListOut])
async def archive_list(
    board_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.list.archive(ctx.actor, board_id, list_id))


@router.post("/boards/{board_id}/lists/{list_id}/restore", response_model=Envelope[ListOut])
async def restore_list(
    board_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.list.restore(ctx.actor, board_id, list_id))


@router.delete("/boards/{board_id}/lists/{list_id}", response_model=Envelope[dict])
async def delete_list(
    board_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.list.delete(ctx.actor, board_id, list_id)
    return ok(request, {"id": list_id, "deleted": True})
