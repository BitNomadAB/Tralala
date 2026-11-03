"""Loop planning, review, generation, readiness, QA and completion routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.envelope import Envelope
from ...schemas.loops import (
    ApprovalOut,
    ApprovalRequest,
    CandidateSubmission,
    DocumentListOut,
    GenerationRequest,
    GenerationRunOut,
    HumanConfirmation,
    ImplementationAcceptance,
    InfoRevisionWrite,
    LoopAgentPreferencesOut,
    LoopAgentPreferencesUpdate,
    LoopCancel,
    LoopContextOut,
    LoopCreate,
    LoopOut,
    LoopUpdate,
    PlanOut,
    QaCycleOut,
    QaDecision,
    QaInstructions,
    QaResultSubmission,
    ReadinessOut,
    WithdrawalOut,
    WithdrawalRequest,
)
from ..deps import RequestContext, get_context, idempotency_key, ok

router = APIRouter(tags=["loops"])


def _agent_preferences(loop_id: str, stored: dict[str, str | None]) -> dict:
    """Purpose-keyed storage, the wire shape the schema names per purpose."""
    return {
        "loop_id": loop_id,
        "analysis_agent_id": stored.get("analysis"),
        "roadmap_agent_id": stored.get("roadmap"),
        "qa_agent_id": stored.get("qa"),
    }


@router.get("/boards/{board_id}/loops", response_model=Envelope[list[LoopOut]])
async def list_loops(
    board_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    include_completed: Annotated[bool, Query()] = False,
    include_archived: Annotated[bool, Query()] = False,
    stage: Annotated[str | None, Query(max_length=40)] = None,
) -> dict:
    ctx.actor.require("loops:read")
    items = ctx.services.loop.list(
        board_id,
        include_completed=include_completed,
        include_archived=include_archived,
        stage=stage,
    )
    return ok(request, items)


@router.post(
    "/boards/{board_id}/loops", response_model=Envelope[LoopOut], status_code=201
)
async def create_loop(
    board_id: str,
    payload: LoopCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    loop, replayed = ctx.services.loop.create(
        ctx.actor, board_id, payload, idempotency_key=key
    )
    if replayed:
        request.state.replayed = True
    return ok(request, loop)


@router.get("/boards/{board_id}/loops/{loop_id}", response_model=Envelope[LoopOut])
async def get_loop(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop.get(board_id, loop_id))


@router.patch("/boards/{board_id}/loops/{loop_id}", response_model=Envelope[LoopOut])
async def update_loop(
    board_id: str,
    loop_id: str,
    payload: LoopUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.loop.update(ctx.actor, board_id, loop_id, payload))


@router.post("/boards/{board_id}/loops/{loop_id}/cancel", response_model=Envelope[LoopOut])
async def cancel_loop(
    board_id: str,
    loop_id: str,
    payload: LoopCancel,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.loop.cancel(ctx.actor, board_id, loop_id, payload))


@router.post("/boards/{board_id}/loops/{loop_id}/archive", response_model=Envelope[LoopOut])
async def archive_loop(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.loop.archive(ctx.actor, board_id, loop_id))


@router.get(
    "/boards/{board_id}/loops/{loop_id}/documents",
    response_model=Envelope[DocumentListOut],
)
async def get_documents(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop_document.documents(board_id, loop_id))


@router.get("/boards/{board_id}/loops/{loop_id}/documents/{kind}/revisions")
async def list_document_revisions(
    board_id: str,
    loop_id: str,
    kind: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    ctx.actor.require("loops:read")
    items, total = ctx.services.loop_document.revision_history(
        board_id, loop_id, kind, limit=limit, offset=offset
    )
    return ok(
        request,
        items,
        {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        },
    )


@router.put(
    "/boards/{board_id}/loops/{loop_id}/documents/info",
    response_model=Envelope[DocumentListOut],
)
async def save_info(
    board_id: str,
    loop_id: str,
    payload: InfoRevisionWrite,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request, ctx.services.loop_document.save_info(ctx.actor, board_id, loop_id, payload)
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/candidates",
    response_model=Envelope[DocumentListOut],
    status_code=201,
)
async def submit_candidate(
    board_id: str,
    loop_id: str,
    payload: CandidateSubmission,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request,
        ctx.services.loop_document.submit_candidate(ctx.actor, board_id, loop_id, payload),
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/reviews/{scope}",
    response_model=Envelope[ApprovalOut],
    status_code=201,
)
async def review_scope(
    board_id: str,
    loop_id: str,
    scope: str,
    payload: ApprovalRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request,
        ctx.services.loop_document.review(ctx.actor, board_id, loop_id, scope, payload),
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/reviews/{scope}/withdraw",
    response_model=Envelope[WithdrawalOut],
)
async def withdraw_review(
    board_id: str,
    loop_id: str,
    scope: str,
    payload: WithdrawalRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    """Take back an approval and empty the documents it authorized. Human only."""
    return ok(
        request,
        ctx.services.loop_document.withdraw(ctx.actor, board_id, loop_id, scope, payload),
    )


@router.get("/boards/{board_id}/loops/{loop_id}/plan", response_model=Envelope[PlanOut])
async def get_plan(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop.plan(board_id, loop_id))


@router.get(
    "/boards/{board_id}/loops/{loop_id}/readiness", response_model=Envelope[ReadinessOut]
)
async def get_readiness(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop.readiness(board_id, loop_id))


@router.get(
    "/boards/{board_id}/loops/{loop_id}/context", response_model=Envelope[LoopContextOut]
)
async def get_context_resource(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop_document.context(board_id, loop_id))


@router.get(
    "/boards/{board_id}/loops/{loop_id}/agents", response_model=Envelope[LoopAgentPreferencesOut]
)
async def get_loop_agents(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    stored = ctx.services.loop_agents.get(board_id, loop_id)
    return ok(request, _agent_preferences(loop_id, stored))


@router.put(
    "/boards/{board_id}/loops/{loop_id}/agents", response_model=Envelope[LoopAgentPreferencesOut]
)
async def set_loop_agents(
    board_id: str,
    loop_id: str,
    payload: LoopAgentPreferencesUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    assignments = {}
    if "analysis_agent_id" in payload.model_fields_set:
        assignments["analysis"] = payload.analysis_agent_id
    if "roadmap_agent_id" in payload.model_fields_set:
        assignments["roadmap"] = payload.roadmap_agent_id
    if "qa_agent_id" in payload.model_fields_set:
        assignments["qa"] = payload.qa_agent_id
    stored = ctx.services.loop_agents.set(ctx.actor, board_id, loop_id, assignments)
    return ok(request, _agent_preferences(loop_id, stored))


@router.post(
    "/boards/{board_id}/loops/{loop_id}/generation-runs",
    response_model=Envelope[GenerationRunOut],
    status_code=202,
)
async def start_generation(
    board_id: str,
    loop_id: str,
    payload: GenerationRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    run, replayed = ctx.services.loop_generation.start(
        ctx.actor, board_id, loop_id, payload, idempotency_key=key
    )
    if replayed:
        request.state.replayed = True
    return ok(request, run)


@router.get(
    "/boards/{board_id}/loops/{loop_id}/generation-runs",
    response_model=Envelope[list[GenerationRunOut]],
)
async def list_generation_runs(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(
        request, ctx.services.loop_generation.list_runs(board_id, loop_id, limit=limit)
    )


@router.get(
    "/boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}",
    response_model=Envelope[GenerationRunOut],
)
async def get_generation_run(
    board_id: str,
    loop_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop_generation.get(board_id, loop_id, run_id))


@router.post(
    "/boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}/cancel",
    response_model=Envelope[GenerationRunOut],
)
async def cancel_generation_run(
    board_id: str,
    loop_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request, ctx.services.loop_generation.cancel(ctx.actor, board_id, loop_id, run_id)
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/generation-runs/{run_id}/retry",
    response_model=Envelope[GenerationRunOut],
    status_code=202,
)
async def retry_generation_run(
    board_id: str,
    loop_id: str,
    run_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    run, replayed = ctx.services.loop_generation.retry(ctx.actor, board_id, loop_id, run_id)
    if replayed:
        request.state.replayed = True
    return ok(request, run)


@router.post(
    "/boards/{board_id}/loops/{loop_id}/completion",
    response_model=Envelope[dict],
)
async def accept_implementation(
    board_id: str,
    loop_id: str,
    payload: ImplementationAcceptance,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request,
        ctx.services.loop_qa.accept_implementation(ctx.actor, board_id, loop_id, payload),
    )


@router.get("/boards/{board_id}/loops/{loop_id}/qa", response_model=Envelope[QaCycleOut])
async def get_qa_cycle(
    board_id: str,
    loop_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("loops:read")
    return ok(request, ctx.services.loop_qa.cycle(board_id, loop_id))


@router.put(
    "/boards/{board_id}/loops/{loop_id}/qa/instructions",
    response_model=Envelope[QaCycleOut],
)
async def submit_qa_instructions(
    board_id: str,
    loop_id: str,
    payload: QaInstructions,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request,
        ctx.services.loop_qa.submit_instructions(ctx.actor, board_id, loop_id, payload),
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/qa/results",
    response_model=Envelope[QaCycleOut],
    status_code=201,
)
async def submit_qa_results(
    board_id: str,
    loop_id: str,
    payload: QaResultSubmission,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(
        request, ctx.services.loop_qa.submit_results(ctx.actor, board_id, loop_id, payload)
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/qa/decision", response_model=Envelope[dict]
)
async def decide_qa(
    board_id: str,
    loop_id: str,
    payload: QaDecision,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    key: Annotated[str | None, Depends(idempotency_key)] = None,
) -> dict:
    return ok(
        request,
        ctx.services.loop_qa.decide(
            ctx.actor, board_id, loop_id, payload, idempotency_key=key
        ),
    )


@router.post(
    "/boards/{board_id}/loops/{loop_id}/cards/{card_id}/confirm",
    response_model=Envelope[dict],
)
async def confirm_human_ticket(
    board_id: str,
    loop_id: str,
    card_id: str,
    payload: HumanConfirmation,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    """A human confirms a human-only Ticket; agents are rejected by the service."""
    return ok(
        request,
        ctx.services.loop.confirm_human_ticket(
            ctx.actor, board_id, loop_id, card_id, payload
        ),
    )


__all__ = ["router"]
