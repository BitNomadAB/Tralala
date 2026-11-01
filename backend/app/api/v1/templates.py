from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...schemas.envelope import Envelope
from ...schemas.templates import (
    TemplateCreate,
    TemplateFromBoard,
    TemplateListOut,
    TemplateOut,
    TemplateUpdate,
)
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=Envelope[TemplateListOut])
async def list_templates(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    items = ctx.services.template.list()
    return ok(request, {"items": items, "total": len(items)})


@router.post("/templates", response_model=Envelope[TemplateOut], status_code=201)
async def create_template(
    payload: TemplateCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.template.create(ctx.actor, payload))


@router.get("/templates/{template_id}", response_model=Envelope[TemplateOut])
async def get_template(
    template_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.template.get(template_id))


@router.patch("/templates/{template_id}", response_model=Envelope[TemplateOut])
async def update_template(
    template_id: str,
    payload: TemplateUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.template.update(ctx.actor, template_id, payload))


@router.delete("/templates/{template_id}", response_model=Envelope[dict])
async def delete_template(
    template_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.template.delete(ctx.actor, template_id)
    return ok(request, {"id": template_id, "deleted": True})


@router.post(
    "/boards/{board_id}/templates",
    response_model=Envelope[TemplateOut],
    status_code=201,
)
async def save_board_as_template(
    board_id: str,
    payload: TemplateFromBoard,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.template.create_from_board(ctx.actor, board_id, payload))


__all__ = ["router"]
