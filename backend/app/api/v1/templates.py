from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...schemas.envelope import Envelope, OpenObject
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
def list_templates(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("boards:read")
    items = ctx.services.template.list()
    return ok(request, {"items": items, "total": len(items)})


@router.post("/templates", response_model=Envelope[TemplateOut], status_code=201)
def create_template(
    payload: TemplateCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.template.create(ctx.actor, payload))


@router.get("/templates/{template_id}", response_model=Envelope[TemplateOut])
def get_template(
    template_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("boards:read")
    return ok(request, ctx.services.template.get(template_id))


@router.patch("/templates/{template_id}", response_model=Envelope[TemplateOut])
def update_template(
    template_id: str,
    payload: TemplateUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.template.update(ctx.actor, template_id, payload))


@router.delete("/templates/{template_id}", response_model=Envelope[OpenObject])
def delete_template(
    template_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.services.template.delete(ctx.actor, template_id)
    return ok(request, {"id": template_id, "deleted": True})


@router.post(
    "/boards/{board_id}/loops/{loop_id}/templates",
    response_model=Envelope[TemplateOut],
    status_code=201,
)
def save_loop_as_template(
    board_id: str,
    loop_id: str,
    payload: TemplateFromBoard,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.template.create_from_loop(ctx.actor, board_id, loop_id, payload),
    )


__all__ = ["router"]
