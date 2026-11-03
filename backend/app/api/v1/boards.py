from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from ...core.errors import PayloadTooLarge
from ...schemas.boards import BoardCreate, BoardDelete, BoardOut, BoardUpdate
from ...schemas.envelope import Envelope
from ..body import read_limited_body
from ..deps import Pagination, RequestContext, get_context, idempotency_key, ok, pagination

router = APIRouter(tags=["boards"])


@router.get("/boards", response_model=Envelope[list[BoardOut]])
def list_boards(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    page: Annotated[Pagination, Depends(pagination)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "updated_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    with_counts: Annotated[bool, Query()] = True,
) -> dict:
    ctx.actor.require("boards:read")
    items, total = ctx.services.board.list(
        q=q,
        status=status,
        sort=sort,
        order=order,
        limit=page.limit,
        offset=page.offset,
        with_counts=with_counts,
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
def create_board(
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
    # Reading the body awaits, so this route stays async and the import runs in the thread pool.
    data = await read_limited_body(request)
    if not data:
        raise PayloadTooLarge("Import payload is empty")
    board = await run_in_threadpool(ctx.services.board.import_archive, ctx.actor, data)
    return ok(request, board)


@router.get("/boards/{board_id}", response_model=Envelope[BoardOut])
def get_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.board.get(board_id))


@router.patch("/boards/{board_id}", response_model=Envelope[BoardOut])
def update_board(
    board_id: str,
    payload: BoardUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.update(ctx.actor, board_id, payload))


@router.post("/boards/{board_id}/archive", response_model=Envelope[BoardOut])
def archive_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.archive(ctx.actor, board_id))


@router.post("/boards/{board_id}/restore", response_model=Envelope[BoardOut])
def restore_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.board.restore(ctx.actor, board_id))


@router.post("/boards/{board_id}/duplicate", response_model=Envelope[BoardOut], status_code=201)
def duplicate_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    name: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    return ok(request, ctx.services.board.duplicate(ctx.actor, board_id, name))


@router.delete("/boards/{board_id}", response_model=Envelope[dict])
def delete_board(
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
def export_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
) -> Response:
    ctx.actor.require("boards:write")
    data = ctx.services.board.export_archive(ctx.actor, board_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="board-{board_id}.zip"'},
    )


@router.get("/boards/{board_id}/actors", response_model=Envelope[dict])
def list_board_actors(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    """Who a worker may assign (`people`) and who it may ask (`agents`).

    A token is its own agent actor and cannot read the user list, so this is the one lookup that
    makes assignment possible without an administrator session.
    """
    ctx.actor.require("boards:read")
    ctx.services.board.require_row(board_id)
    return ok(
        request,
        {
            "people": ctx.services.agent.assignable_people(),
            "agents": ctx.services.agent.askable_agents(board_id),
        },
    )


@router.get("/boards/{board_id}/validate", response_model=Envelope[dict])
def validate_board(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.backup.validate(board_id))


@router.post("/boards/{board_id}/migrate", response_model=Envelope[dict])
def retry_board_migration(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:admin")
    report = ctx.services.migrations.migrate_board(board_id)
    return ok(request, report.to_dict())


@router.get("/boards/{board_id}/backups", response_model=Envelope[list[dict]])
def list_backups(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.backup.list(board_id))


@router.post("/boards/{board_id}/backups", response_model=Envelope[dict], status_code=201)
def create_backup(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.backup.create(ctx.actor, board_id))


@router.post("/boards/{board_id}/backups/{name}/restore", response_model=Envelope[dict])
def restore_backup(
    board_id: str,
    name: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.backup.restore(ctx.actor, board_id, name))


__all__ = ["router"]
