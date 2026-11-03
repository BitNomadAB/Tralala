from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from ...core.errors import PayloadTooLarge
from ...schemas.attachments import AttachmentOut
from ...schemas.envelope import Envelope
from ..body import read_limited_body
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["attachments"])


@router.get("/boards/{board_id}/attachments", response_model=Envelope[list[AttachmentOut]])
def list_attachments(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    card_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    ctx.actor.require("cards:read")
    return ok(request, ctx.services.attachment.list(board_id, card_id=card_id))


@router.post(
    "/boards/{board_id}/attachments", response_model=Envelope[AttachmentOut], status_code=201
)
async def upload_attachment(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    card_id: Annotated[str, Query(max_length=64)],
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> dict:
    # Reading the body awaits, so this route stays async and the upload runs in the thread pool.
    data = await read_limited_body(request)
    if not data:
        raise PayloadTooLarge("Uploaded file is empty")
    attachment = await run_in_threadpool(
        ctx.services.attachment.upload,
        ctx.actor,
        board_id,
        card_id=card_id,
        filename=filename,
        content_type=request.headers.get("content-type"),
        data=data,
    )
    return ok(request, attachment)


@router.get(
    "/boards/{board_id}/attachments/{attachment_id}",
    response_model=Envelope[AttachmentOut],
)
def get_attachment(
    board_id: str,
    attachment_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("cards:read")
    return ok(request, ctx.services.attachment.get(board_id, attachment_id))


@router.get("/boards/{board_id}/attachments/{attachment_id}/download")
def download_attachment(
    board_id: str,
    attachment_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
) -> Response:
    ctx.actor.require("cards:read")
    row, data = ctx.services.attachment.read_bytes(board_id, attachment_id)
    filename = row["original_filename"]
    return Response(
        content=data,
        media_type=row["content_type"],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, max-age=0, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/boards/{board_id}/attachments/{attachment_id}", response_model=Envelope[dict])
def delete_attachment(
    board_id: str,
    attachment_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.attachment.delete(ctx.actor, board_id, attachment_id)
    return ok(request, {"id": attachment_id, "deleted": True})


__all__ = ["router"]
