"""Board-local history browsing and the legacy-import boundary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.loops import HistoryDetail, HistorySummary, LegacyImportRequest
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["history"])


@router.get("/boards/{board_id}/history", response_model=Envelope[list[HistorySummary]])
def search_history(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    q: Annotated[str | None, Query(max_length=300)] = None,
    source_kind: Annotated[str | None, Query(max_length=40)] = None,
    loop_key: Annotated[str | None, Query(max_length=120)] = None,
    qa_status: Annotated[str | None, Query(max_length=40)] = None,
    date_from: Annotated[str | None, Query(max_length=40)] = None,
    date_to: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    ctx.actor.require("history:read")
    result = ctx.services.loop_history.search(
        board_id,
        q=q,
        source_kind=source_kind,
        loop_key=loop_key,
        qa_status=qa_status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
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


@router.get("/boards/{board_id}/history/{history_id}", response_model=Envelope[HistoryDetail])
def get_history_record(
    board_id: str,
    history_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("history:read")
    return ok(request, ctx.services.loop_history.detail(board_id, history_id))


@router.post(
    "/boards/{board_id}/history/import",
    response_model=Envelope[HistoryDetail],
    status_code=201,
)
def import_legacy_record(
    board_id: str,
    payload: LegacyImportRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    record, replayed = ctx.services.loop_history.import_legacy(ctx.actor, board_id, payload)
    if replayed:
        request.state.replayed = True
    return ok(request, record)


__all__ = ["router"]
