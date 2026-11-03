"""Loop-scoped Kanban column routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope, OpenObject
from ...schemas.lists import ListCreate, ListMove, ListOut, ListUpdate
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["lists"])

PREFIX = "/boards/{board_id}/loops/{loop_id}/lists"


@router.get(PREFIX, response_model=Envelope[list[ListOut]])
def list_lists(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    include_archived: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    ctx.actor.require("cards:read")
    return ok(
        request,
        ctx.services.list.list(board_id, loop_id, include_archived=include_archived),
    )


@router.post(PREFIX, response_model=Envelope[ListOut], status_code=201)
def create_list(
    board_id: str,
    loop_id: str,
    payload: ListCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.list.create(ctx.actor, board_id, loop_id, payload))


@router.get(f"{PREFIX}/{{list_id}}", response_model=Envelope[ListOut])
def get_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("cards:read")
    return ok(request, ctx.services.list.get(board_id, loop_id, list_id))


@router.patch(f"{PREFIX}/{{list_id}}", response_model=Envelope[ListOut])
def update_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    payload: ListUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request, ctx.services.list.update(ctx.actor, board_id, loop_id, list_id, payload)
    )


@router.post(f"{PREFIX}/{{list_id}}/move", response_model=Envelope[list[ListOut]])
def move_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    payload: ListMove,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request, ctx.services.list.move(ctx.actor, board_id, loop_id, list_id, payload)
    )


@router.post(f"{PREFIX}/{{list_id}}/archive", response_model=Envelope[ListOut])
def archive_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.list.archive(ctx.actor, board_id, loop_id, list_id))


@router.post(f"{PREFIX}/{{list_id}}/restore", response_model=Envelope[ListOut])
def restore_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.list.restore(ctx.actor, board_id, loop_id, list_id))


@router.delete(f"{PREFIX}/{{list_id}}", response_model=Envelope[OpenObject])
def delete_list(
    board_id: str,
    loop_id: str,
    list_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.services.list.delete(ctx.actor, board_id, loop_id, list_id)
    return ok(request, {"id": list_id, "deleted": True})


__all__ = ["router"]
