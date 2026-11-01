"""GitHub repositories, managed from the administrator page and assigned to boards."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.repositories import (
    RepositoryCheckOut,
    RepositoryCreate,
    RepositoryOut,
    RepositoryUpdate,
)
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["repositories"])


def _sees_health(ctx: RequestContext) -> bool:
    """Credential hints and check outcomes belong to whoever may administer repositories."""
    return ctx.actor.has_scope("boards:admin")


@router.get(
    "/repositories",
    response_model=Envelope[list[RepositoryOut]],
    response_model_exclude_none=True,
)
async def list_repositories(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    board_id: Annotated[str | None, Query()] = None,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(
        request,
        ctx.services.repository.list(
            board_id=board_id, with_health=_sees_health(ctx)
        ),
    )


@router.post("/repositories", response_model=Envelope[RepositoryOut], status_code=201)
async def create_repository(
    payload: RepositoryCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.repository.create(ctx.actor, payload))


@router.get(
    "/repositories/{repository_id}",
    response_model=Envelope[RepositoryOut],
    response_model_exclude_none=True,
)
async def get_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("boards:read")
    return ok(
        request,
        ctx.services.repository.get(repository_id, with_health=_sees_health(ctx)),
    )


@router.patch("/repositories/{repository_id}", response_model=Envelope[RepositoryOut])
async def update_repository(
    repository_id: str,
    payload: RepositoryUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.repository.update(ctx.actor, repository_id, payload))


@router.delete("/repositories/{repository_id}", response_model=Envelope[dict])
async def delete_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.repository.delete(ctx.actor, repository_id)
    return ok(request, {"deleted": True})


@router.post("/repositories/{repository_id}/check", response_model=Envelope[RepositoryCheckOut])
async def check_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.repository.check(ctx.actor, repository_id))
