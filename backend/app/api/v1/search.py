from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.cards import CardOut
from ...schemas.envelope import Envelope
from ...schemas.subresources import ActivityOut
from ..deps import Pagination, RequestContext, get_context, ok, pagination

router = APIRouter(tags=["search"])


@router.get(
    "/boards/{board_id}/loops/{loop_id}/search", response_model=Envelope[list[CardOut]]
)
async def search_board(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    page: Annotated[Pagination, Depends(pagination)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    priority: Annotated[str | None, Query()] = None,
    label: Annotated[str | None, Query()] = None,
    completed: Annotated[bool | None, Query()] = None,
    overdue: Annotated[bool, Query()] = False,
    list_id: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> dict:
    ctx.actor.require("cards:read")
    result = ctx.services.search.board(
        board_id,
        loop_id,
        q=q,
        priority=priority,
        label=label,
        completed=completed,
        overdue=overdue,
        list_id=list_id,
        include_archived=include_archived,
        limit=page.limit,
        offset=page.offset,
    )
    return ok(
        request,
        result["items"],
        {
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
            "has_more": result["has_more"],
            "engine": result["engine"],
        },
    )


@router.get("/search", response_model=Envelope[list[CardOut]])
async def search_all_boards(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    ctx.actor.require("cards:read")
    result = ctx.services.search.global_search(q=q, limit_per_loop=limit)
    return ok(
        request,
        result["items"],
        {
            "board_count": result["board_count"],
            "loop_count": result["loop_count"],
            "query": q,
        },
    )


@router.get("/boards/{board_id}/activity", response_model=Envelope[list[ActivityOut]])
async def activity(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    page: Annotated[Pagination, Depends(pagination)],
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    actor_type: Annotated[str | None, Query(pattern="^(user|agent|service)$")] = None,
    action: Annotated[str | None, Query()] = None,
) -> dict:
    ctx.actor.require("boards:read")
    ctx.actor.require("cards:read")
    from ...services.search import activity_feed

    items, total = activity_feed(
        board_id,
        ctx.services.board,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        action=action,
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
