from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...schemas.envelope import Envelope
from ...schemas.subresources import (
    ChecklistCreate,
    ChecklistItemCreate,
    ChecklistItemOut,
    ChecklistItemUpdate,
    ChecklistOut,
    ChecklistUpdate,
    CommentCreate,
    CommentOut,
    LabelCreate,
    LabelOut,
    LabelUpdate,
)
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["labels"])


@router.get("/boards/{board_id}/labels", response_model=Envelope[list[LabelOut]])
async def list_labels(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("cards:read")
    return ok(request, ctx.services.label.list(board_id))


@router.post("/boards/{board_id}/labels", response_model=Envelope[LabelOut], status_code=201)
async def create_label(
    board_id: str,
    payload: LabelCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.label.create(ctx.actor, board_id, payload))


@router.patch("/boards/{board_id}/labels/{label_id}", response_model=Envelope[LabelOut])
async def update_label(
    board_id: str,
    label_id: str,
    payload: LabelUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.label.update(ctx.actor, board_id, label_id, payload))


@router.delete("/boards/{board_id}/labels/{label_id}", response_model=Envelope[dict])
async def delete_label(
    board_id: str,
    label_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.label.delete(ctx.actor, board_id, label_id)
    return ok(request, {"id": label_id, "deleted": True})


checklists = APIRouter(tags=["checklists"])


@checklists.patch(
    "/boards/{board_id}/checklists/{checklist_id}", response_model=Envelope[ChecklistOut]
)
async def update_checklist(
    board_id: str,
    checklist_id: str,
    payload: ChecklistUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.checklist.update(ctx.actor, board_id, checklist_id, payload))


@checklists.delete("/boards/{board_id}/checklists/{checklist_id}", response_model=Envelope[dict])
async def delete_checklist(
    board_id: str,
    checklist_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.checklist.delete(ctx.actor, board_id, checklist_id)
    return ok(request, {"id": checklist_id, "deleted": True})


@checklists.post(
    "/boards/{board_id}/checklists/{checklist_id}/items",
    response_model=Envelope[ChecklistItemOut],
    status_code=201,
)
async def add_checklist_item(
    board_id: str,
    checklist_id: str,
    payload: ChecklistItemCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.checklist.add_item(ctx.actor, board_id, checklist_id, payload))


@checklists.patch(
    "/boards/{board_id}/checklist-items/{item_id}", response_model=Envelope[ChecklistItemOut]
)
async def update_checklist_item(
    board_id: str,
    item_id: str,
    payload: ChecklistItemUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.checklist.update_item(ctx.actor, board_id, item_id, payload))


@checklists.delete("/boards/{board_id}/checklist-items/{item_id}", response_model=Envelope[dict])
async def delete_checklist_item(
    board_id: str,
    item_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.checklist.delete_item(ctx.actor, board_id, item_id)
    return ok(request, {"id": item_id, "deleted": True})


comments = APIRouter(tags=["comments"])


@comments.patch("/boards/{board_id}/comments/{comment_id}", response_model=Envelope[CommentOut])
async def update_comment(
    board_id: str,
    comment_id: str,
    payload: CommentCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.comment.update(ctx.actor, board_id, comment_id, payload))


@comments.delete("/boards/{board_id}/comments/{comment_id}", response_model=Envelope[dict])
async def delete_comment(
    board_id: str,
    comment_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.comment.delete(ctx.actor, board_id, comment_id)
    return ok(request, {"id": comment_id, "deleted": True})


__all__ = ["ChecklistCreate", "checklists", "comments", "router"]
