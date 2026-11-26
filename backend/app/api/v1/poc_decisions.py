"""A Loop's POC decisions, what is missing from a person, and its stop list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.poc_decisions import (
    PocDecisionAnswerCreate,
    PocDecisionCreate,
    PocDecisionListOut,
    PocDecisionOut,
    PocDecisionRecordedOut,
    PocStatus,
    StopListOut,
    StopListUpdate,
)
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["loops"])

DECISIONS = "/boards/{board_id}/loops/{loop_id}/poc-decisions"
STOPS = "/boards/{board_id}/loops/{loop_id}/stops"


@router.get(DECISIONS, response_model=Envelope[PocDecisionListOut])
def list_poc_decisions(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    card_id: Annotated[str | None, Query(max_length=64)] = None,
    status: PocStatus | None = None,
) -> dict[str, object]:
    """The Loop's records in review order, with the counts over all of them."""
    found = ctx.services.poc_decisions.list(
        ctx.actor, board_id, loop_id, card_id=card_id or None, status=status
    )
    return ok(request, found)


@router.post(DECISIONS, response_model=Envelope[PocDecisionRecordedOut], status_code=201)
def record_poc_decision(
    board_id: str,
    loop_id: str,
    payload: PocDecisionCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """Record a POC decision or something missing (422 poc_decision_invalid); the same open
    record again answers the first one with deduplicated true."""
    recorded = ctx.services.poc_decisions.record(ctx.actor, board_id, loop_id, payload)
    return ok(request, recorded)


@router.post(f"{DECISIONS}/{{decision_id}}/answer", response_model=Envelope[PocDecisionOut])
def answer_poc_decision(
    board_id: str,
    loop_id: str,
    decision_id: str,
    payload: PocDecisionAnswerCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """A person's OK or feedback (403 human_action_required for a key, 409
    poc_decision_answered once it was answered with feedback)."""
    answered = ctx.services.poc_decisions.answer(
        ctx.actor, board_id, loop_id, decision_id, payload
    )
    return ok(request, answered)


@router.get(STOPS, response_model=Envelope[StopListOut])
def read_stops(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """The Loop's stop list; is_default while no person has written one."""
    return ok(request, ctx.services.loop_stops.read(ctx.actor, board_id, loop_id))


@router.put(STOPS, response_model=Envelope[StopListOut])
def write_stops(
    board_id: str,
    loop_id: str,
    payload: StopListUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict[str, object]:
    """A person's stop list (403 human_action_required for a key, 422 stops_invalid)."""
    stops = ctx.services.loop_stops.write(ctx.actor, board_id, loop_id, payload.stops)
    return ok(request, stops)
