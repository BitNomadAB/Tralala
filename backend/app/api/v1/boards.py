from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from ...core.errors import PayloadTooLarge
from ...schemas.boards import BoardCreate, BoardDelete, BoardOut, BoardUpdate
from ...schemas.envelope import Envelope
from ..deps import Pagination, RequestContext, get_context, idempotency_key, ok, pagination

router = APIRouter(tags=["boards"])


@router.get("/boards", response_model=Envelope[list[BoardOut]])
async def list_boards(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    page: Annotated[Pagination, Depends(pagination)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "updated_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> dict:
    ctx.actor.require("boards:read")
    items, total = ctx.services.board.list(
        q=q,
        status=status,
        sort=sort,
        order=order,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(
        request,
        items,
        {
            "total": total,
            "limit": page.limit,
            "offset": page.offset,
            "has_more": page.offset + page.limit < total,
        },
    )


@router.post("/boards", response_model=Envelope[BoardOut], status_code=201)
async def create_board(
    payload: BoardCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    board, replayed = ctx.services.board.create(ctx.actor, payload, idempotency_key=key)
    if replayed:
        request.state.replayed = True
    return ok(request, board)


@router.post("/boards/import", response_model=Envelope[BoardOut], status_code=201)
async def import_board(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    data = await request.body()
    if not data:
        raise PayloadTooLarge("Import payload is empty")
    if len(data) > ctx.services.settings.max_request_bytes:
        raise PayloadTooLarge("Import payload exceeds the configured limit")
    board = ctx.services.board.import_archive(ctx.actor, data)
    return ok(request, board)


@router.get("/boards/{board_id}", response_model=Envelope[BoardOut])
async def get_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.board.get(board_id))


@router.patch("/boards/{board_id}", response_model=Envelope[BoardOut])
async def update_board(
    board_id: str,
    payload: BoardUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.update(ctx.actor, board_id, payload))


@router.post("/boards/{board_id}/archive", response_model=Envelope[BoardOut])
async def archive_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.archive(ctx.actor, board_id))


@router.post("/boards/{board_id}/restore", response_model=Envelope[BoardOut])
async def restore_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.restore(ctx.actor, board_id))


@router.post("/boards/{board_id}/duplicate", response_model=Envelope[BoardOut], status_code=201)
async def duplicate_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    name: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    return ok(request, ctx.services.board.duplicate(ctx.actor, board_id, name))


@router.delete("/boards/{board_id}", response_model=Envelope[dict])
async def delete_board(
    board_id: str,
    payload: BoardDelete,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.board.delete(ctx.actor, board_id, payload.confirm_name)
    return ok(request, {"id": board_id, "deleted": True})


@router.get(
    "/boards/{board_id}/export",
    responses={200: {"content": {"application/zip": {}}, "description": "Board export archive"}},
)
async def export_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> Response:
    ctx.actor.require("boards:write")
    data = ctx.services.board.export_archive(ctx.actor, board_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="board-{board_id}.zip"'},
    )


@router.get("/boards/{board_id}/validate", response_model=Envelope[dict])
async def validate_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.backup.validate(board_id))


@router.post("/boards/{board_id}/migrate", response_model=Envelope[dict])
async def retry_board_migration(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:admin")
    report = ctx.services.migrations.migrate_board(board_id)
    return ok(request, report.to_dict())


@router.get("/boards/{board_id}/backups", response_model=Envelope[list[dict]])
async def list_backups(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.backup.list(board_id))


@router.post("/boards/{board_id}/backups", response_model=Envelope[dict], status_code=201)
async def create_backup(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.backup.create(ctx.actor, board_id))


@router.post("/boards/{board_id}/backups/{name}/restore", response_model=Envelope[dict])
async def restore_backup(
    board_id: str,
    name: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.backup.restore(ctx.actor, board_id, name))


__all__ = ["router"]
