from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ...schemas.discussions import (
    DiscussionCreate,
    DiscussionEventListOut,
    DiscussionInboxOut,
    DiscussionListOut,
    DiscussionMessageCreate,
    DiscussionOut,
    DiscussionReview,
    DiscussionRunListOut,
    DiscussionRunOut,
    DiscussionRunStart,
)
from ...schemas.envelope import Envelope, OpenObject
from ..deps import RequestContext, get_context, ok
from .streaming import STREAM_HEADERS, event_stream

router = APIRouter(tags=["discussions"])


@router.get("/discussions/inbox", response_model=Envelope[DiscussionInboxOut])
def discussion_inbox(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.discussion.inbox(ctx.actor))


@router.get("/boards/{board_id}/discussions", response_model=Envelope[DiscussionListOut])
def list_discussions(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    status: Annotated[str | None, Query(max_length=40)] = None,
    card_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    ctx.actor.require("discussions:read")
    items = ctx.services.discussion.list(board_id, status=status, card_id=card_id, limit=limit)
    return ok(request, {"items": items, "total": len(items)})


@router.post(
    "/boards/{board_id}/discussions", response_model=Envelope[DiscussionOut], status_code=201
)
def create_discussion(
    board_id: str,
    payload: DiscussionCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.discussion.create(ctx.actor, board_id, payload))


@router.get(
    "/boards/{board_id}/discussions/{discussion_id}",
    response_model=Envelope[DiscussionOut],
)
def get_discussion(
    board_id: str,
    discussion_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("discussions:read")
    return ok(request, ctx.services.discussion.get(board_id, discussion_id))


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/start",
    response_model=Envelope[OpenObject],
)
def start_discussion(
    board_id: str,
    discussion_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    payload: DiscussionRunStart | None = None,
) -> dict[str, object]:
    options = payload or DiscussionRunStart()
    return ok(
        request,
        ctx.services.run.start(
            ctx.actor,
            board_id,
            discussion_id,
            rounds=options.rounds,
            autonomous=options.autonomous,
            token_budget=options.token_budget,
            time_budget_seconds=options.time_budget_seconds,
        ),
    )


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/runs",
    response_model=Envelope[OpenObject],
    status_code=202,
)
def create_run(
    board_id: str,
    discussion_id: str,
    payload: DiscussionRunStart,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.run.start(
            ctx.actor,
            board_id,
            discussion_id,
            rounds=payload.rounds,
            autonomous=payload.autonomous,
            token_budget=payload.token_budget,
            time_budget_seconds=payload.time_budget_seconds,
            background=True,
        ),
    )


@router.get(
    "/boards/{board_id}/discussions/{discussion_id}/runs",
    response_model=Envelope[DiscussionRunListOut],
)
def list_runs(
    board_id: str,
    discussion_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    ctx.actor.require("discussions:read")
    items = ctx.services.run.list(board_id, discussion_id, limit=limit)
    return ok(request, {"items": items, "total": len(items)})


@router.get(
    "/boards/{board_id}/discussions/{discussion_id}/runs/{run_id}",
    response_model=Envelope[DiscussionRunOut],
)
def get_run(
    board_id: str,
    discussion_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    ctx.actor.require("discussions:read")
    return ok(request, ctx.services.run.get(board_id, discussion_id, run_id))


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/runs/{run_id}/pause",
    response_model=Envelope[OpenObject],
)
def pause_run(
    board_id: str,
    discussion_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.run.pause(ctx.actor, board_id, discussion_id, run_id))


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/runs/{run_id}/resume",
    response_model=Envelope[OpenObject],
)
def resume_run(
    board_id: str,
    discussion_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.run.resume(ctx.actor, board_id, discussion_id, run_id))


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/runs/{run_id}/stop",
    response_model=Envelope[OpenObject],
)
def stop_run(
    board_id: str,
    discussion_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(request, ctx.services.run.stop(ctx.actor, board_id, discussion_id, run_id))



@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/review",
    response_model=Envelope[DiscussionOut],
)
def review_discussion(
    board_id: str,
    discussion_id: str,
    payload: DiscussionReview,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request,
        ctx.services.discussion.review(
            ctx.actor,
            board_id,
            discussion_id,
            decision=payload.decision,
            reason=payload.reason,
        ),
    )


@router.post(
    "/boards/{board_id}/discussions/{discussion_id}/messages",
    response_model=Envelope[DiscussionOut],
    status_code=201,
)
def post_discussion_message(
    board_id: str,
    discussion_id: str,
    payload: DiscussionMessageCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    return ok(
        request, ctx.services.discussion.add_message(ctx.actor, board_id, discussion_id, payload)
    )


@router.get(
    "/boards/{board_id}/discussions/{discussion_id}/events/history",
    response_model=Envelope[DiscussionEventListOut],
)
def discussion_event_history(
    board_id: str,
    discussion_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, object]:
    ctx.actor.require("discussions:read")
    items = ctx.services.event.replay(board_id, discussion_id, after=after, limit=limit)
    return ok(request, {"items": items, "total": len(items)})


@router.get(
    "/boards/{board_id}/discussions/{discussion_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent events for one discussion thread.",
        }
    },
)
def discussion_event_stream(
    board_id: str,
    discussion_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Replay what the client missed, then stream live events.

    The client's `Last-Event-ID` (sent automatically by `EventSource` on reconnect) wins over the
    query parameter. Subscribing before the replay closes the window where an event commits
    between the two steps; `last` drops the duplicate in that case.
    """
    ctx.actor.require("discussions:read")
    events = ctx.services.event
    events.ensure_discussion(board_id, discussion_id)
    header_id = request.headers.get("last-event-id", "").strip()
    if header_id.isdigit():
        after = max(after, int(header_id))
    return StreamingResponse(
        event_stream(
            request,
            after=after,
            subscribe=lambda: events.subscribe(board_id, discussion_id),
            unsubscribe=lambda listener: events.unsubscribe(board_id, discussion_id, listener),
            replay=lambda: events.replay(board_id, discussion_id, after=after),
        ),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


__all__ = ["router"]
