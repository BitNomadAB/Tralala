"""Code repositories (GitHub, or a Git mirror of an allowed HTTPS host), managed from the
administrator page and assigned to boards."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope, OpenObject
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
def list_repositories(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    board_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    ctx.actor.require("boards:read")
    return ok(
        request,
        ctx.services.repository.list(
            board_id=board_id, with_health=_sees_health(ctx)
        ),
    )


@router.post("/repositories", response_model=Envelope[RepositoryOut], status_code=201)
def create_repository(
    payload: RepositoryCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.repository.create(ctx.actor, payload))


@router.get(
    "/repositories/{repository_id}",
    response_model=Envelope[RepositoryOut],
    response_model_exclude_none=True,
)
def get_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("boards:read")
    return ok(
        request,
        ctx.services.repository.get(repository_id, with_health=_sees_health(ctx)),
    )


@router.patch("/repositories/{repository_id}", response_model=Envelope[RepositoryOut])
def update_repository(
    repository_id: str,
    payload: RepositoryUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.repository.update(ctx.actor, repository_id, payload))


@router.delete("/repositories/{repository_id}", response_model=Envelope[OpenObject])
def delete_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.services.repository.delete(ctx.actor, repository_id)
    return ok(request, {"deleted": True})


@router.post("/repositories/{repository_id}/check", response_model=Envelope[RepositoryCheckOut])
def check_repository(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.repository.check(ctx.actor, repository_id))


@router.post("/repositories/{repository_id}/mirror/remove", response_model=Envelope[RepositoryOut])
def remove_repository_mirror(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """Remove now: a ``git_https`` repository's mirror goes; ``409 mirror_cleanup_failed`` when the
    host still holds a file in it."""
    return ok(request, ctx.services.repository.remove_mirror(ctx.actor, repository_id))


@router.post("/repositories/{repository_id}/mirror/rebuild", response_model=Envelope[RepositoryOut])
def rebuild_repository_mirror(
    repository_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """Rebuild mirror: the mirror goes now, and the next run clones the repository again."""
    return ok(request, ctx.services.repository.remove_mirror(ctx.actor, repository_id))
