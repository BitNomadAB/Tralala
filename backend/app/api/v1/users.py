from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...schemas.auth import (
    InviteCreate,
    InviteCreated,
    UserCreate,
    UserOut,
    UserPasswordReset,
    UserUpdate,
)
from ...schemas.envelope import Envelope, OpenObject
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["users"])


@router.get("/users", response_model=Envelope[list[UserOut]])
def list_users(
    ctx: Annotated[RequestContext, Depends(get_context)], request: Request
) -> dict[str, object]:
    return ok(request, ctx.services.auth.list_users(ctx.actor))


@router.post("/users", response_model=Envelope[UserOut], status_code=201)
def create_user(
    payload: UserCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.auth.create_user(
            ctx.actor, name=payload.name, password=payload.password, role=payload.role
        ),
    )


@router.patch("/users/{user_id}", response_model=Envelope[UserOut])
def update_user(
    user_id: str,
    payload: UserUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.auth.update_user(
            ctx.actor, user_id, role=payload.role, disabled=payload.disabled
        ),
    )


@router.post("/users/{user_id}/password", response_model=Envelope[OpenObject])
def reset_user_password(
    user_id: str,
    payload: UserPasswordReset,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request, ctx.services.auth.reset_password(ctx.actor, user_id, payload.new_password)
    )


@router.post("/users/{user_id}/invite", response_model=Envelope[InviteCreated], status_code=201)
def invite_user(
    user_id: str,
    payload: InviteCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.auth.create_invite(
            ctx.actor, user_id, expires_in_hours=payload.expires_in_hours
        ),
    )
