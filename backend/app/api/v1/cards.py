"""Ticket routes: Loop-scoped Kanban cards plus their Loop-addressed subresources."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ...schemas.cards import (
    BoardTicketOut,
    BulkCardCreate,
    BulkCreateResult,
    CardCreate,
    CardMove,
    CardOut,
    CardUpdate,
)
from ...schemas.envelope import Envelope
from ...schemas.subresources import (
    CardEventListOut,
    ChecklistCreate,
    ChecklistOut,
    CommentCreate,
    CommentMentionOut,
    CommentOut,
)
from ..deps import Pagination, RequestContext, get_context, idempotency_key, ok, pagination
from .streaming import STREAM_HEADERS, event_stream

router = APIRouter(tags=["cards"])

PREFIX = "/boards/{board_id}/loops/{loop_id}/cards"


@router.get("/boards/{board_id}/tickets", response_model=Envelope[list[BoardTicketOut]])
def list_board_tickets(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    """Aggregate read across every active Loop; each item names its owning Loop."""
    ctx.actor.require("cards:read")
    items = ctx.services.card.list_board_tickets(board_id, q=q, limit=limit)
    return ok(request, items)


@router.get(PREFIX, response_model=Envelope[list[CardOut]])
def list_cards(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    page: Annotated[Pagination, Depends(pagination)],
    list_id: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    label: Annotated[str | None, Query()] = None,
    priority: Annotated[str | None, Query()] = None,
    due_before: Annotated[str | None, Query()] = None,
    overdue: Annotated[bool, Query()] = False,
    completed: Annotated[bool | None, Query()] = None,
    assignee: Annotated[str | None, Query(max_length=64)] = None,
    include_archived: Annotated[bool, Query()] = False,
    sort: Annotated[str, Query()] = "position",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
) -> dict:
    ctx.actor.require("cards:read")
    items, total = ctx.services.card.list(
        board_id,
        loop_id,
        list_id=list_id,
        q=q,
        label=label,
        priority=priority,
        due_before=due_before,
        overdue=overdue,
        completed=completed,
        assignee=ctx.actor.actor_id if assignee == "me" else assignee,
        include_archived=include_archived,
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


@router.post(PREFIX, response_model=Envelope[CardOut], status_code=201)
def create_card(
    board_id: str,
    loop_id: str,
    payload: CardCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    card, replayed = ctx.services.card.create(
        ctx.actor, board_id, loop_id, payload, idempotency_key=key
    )
    if replayed:
        request.state.replayed = True
    return ok(request, card)


@router.post(f"{PREFIX}/bulk", response_model=Envelope[BulkCreateResult], status_code=201)
def bulk_create_cards(
    board_id: str,
    loop_id: str,
    payload: BulkCardCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    result, replayed = ctx.services.card.bulk_create(
        ctx.actor, board_id, loop_id, payload, idempotency_key=key
    )
    if replayed:
        request.state.replayed = True
    return ok(request, result)


@router.get(f"{PREFIX}/{{card_id}}", response_model=Envelope[CardOut])
def get_card(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    include: Annotated[str | None, Query(description="Comma list: checklists,comments")] = None,
) -> dict:
    ctx.actor.require("cards:read")
    card = ctx.services.card.get(board_id, loop_id, card_id)
    requested = {part.strip() for part in (include or "").split(",") if part.strip()}
    if "checklists" in requested:
        card["checklists"] = ctx.services.checklist.list(board_id, card_id)
    if "comments" in requested:
        card["comments"] = ctx.services.comment.list(board_id, card_id)
    return ok(request, card)


@router.patch(f"{PREFIX}/{{card_id}}", response_model=Envelope[CardOut])
def update_card(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: CardUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request, ctx.services.card.update(ctx.actor, board_id, loop_id, card_id, payload)
    )


@router.post(f"{PREFIX}/{{card_id}}/move", response_model=Envelope[CardOut])
def move_card(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: CardMove,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.card.move(ctx.actor, board_id, loop_id, card_id, payload))


@router.post(f"{PREFIX}/{{card_id}}/archive", response_model=Envelope[CardOut])
def archive_card(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.card.archive(ctx.actor, board_id, loop_id, card_id))


@router.post(f"{PREFIX}/{{card_id}}/restore", response_model=Envelope[CardOut])
def restore_card(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.card.restore(ctx.actor, board_id, loop_id, card_id))


@router.get(f"{PREFIX}/{{card_id}}/comments", response_model=Envelope[list[CommentOut]])
def list_comments(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("cards:read")
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.comment.list(board_id, card_id))


@router.post(
    f"{PREFIX}/{{card_id}}/comments",
    response_model=Envelope[CommentOut],
    status_code=201,
)
def add_comment(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: CommentCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.comment.create(ctx.actor, board_id, card_id, payload))


@router.get(
    f"{PREFIX}/{{card_id}}/mentions", response_model=Envelope[list[CommentMentionOut]]
)
def list_mentions(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("cards:read")
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.mention.list(board_id, card_id))


@router.post(
    f"{PREFIX}/{{card_id}}/mentions/{{job_id}}/retry",
    response_model=Envelope[CommentMentionOut],
    status_code=202,
)
def retry_mention(
    board_id: str,
    loop_id: str,
    card_id: str,
    job_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.mention.retry(ctx.actor, board_id, card_id, job_id))


@router.get(
    f"{PREFIX}/{{card_id}}/events/history", response_model=Envelope[CardEventListOut]
)
def card_event_history(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    ctx.actor.require("cards:read")
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    items = ctx.services.event.replay_card(board_id, card_id, after=after, limit=limit)
    return ok(request, {"items": items, "total": len(items)})


@router.get(
    f"{PREFIX}/{{card_id}}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events for one ticket (agent mention work).",
        }
    },
)
def card_event_stream(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Replay missed ticket events, then stream live ones; see the discussion stream."""
    ctx.actor.require("cards:read")
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    events = ctx.services.event
    events.ensure_card(board_id, card_id)
    header_id = request.headers.get("last-event-id", "").strip()
    if header_id.isdigit():
        after = max(after, int(header_id))
    return StreamingResponse(
        event_stream(
            request,
            after=after,
            subscribe=lambda: events.subscribe_card(board_id, card_id),
            unsubscribe=lambda listener: events.unsubscribe_card(board_id, card_id, listener),
            replay=lambda: events.replay_card(board_id, card_id, after=after),
        ),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@router.get(f"{PREFIX}/{{card_id}}/checklists", response_model=Envelope[list[ChecklistOut]])
def list_checklists(
    board_id: str,
    loop_id: str,
    card_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("cards:read")
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.checklist.list(board_id, card_id))


@router.post(
    f"{PREFIX}/{{card_id}}/checklists",
    response_model=Envelope[ChecklistOut],
    status_code=201,
)
def create_checklist(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: ChecklistCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.card.require_membership(board_id, loop_id, card_id)
    return ok(request, ctx.services.checklist.create(ctx.actor, board_id, card_id, payload))


__all__ = ["router"]
