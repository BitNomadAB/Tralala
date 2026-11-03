from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ...schemas.agents import (
    AgentCreate,
    AgentDirectoryEntry,
    AgentDuplicate,
    AgentOut,
    AgentTestRequest,
    AgentTestResult,
    AgentUpdate,
    RoleTemplateCreate,
    RoleTemplateDuplicate,
    RoleTemplateOut,
    RoleTemplateUpdate,
)
from ...schemas.envelope import Envelope
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["agents"])


@router.get("/role-templates", response_model=Envelope[list[RoleTemplateOut]])
def list_role_templates(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("agents:read")
    return ok(request, ctx.services.role_templates.list())


@router.post("/role-templates", response_model=Envelope[RoleTemplateOut], status_code=201)
def create_role_template(
    payload: RoleTemplateCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.role_templates.create(ctx.actor, payload))


@router.get("/role-templates/{role_id}", response_model=Envelope[RoleTemplateOut])
def get_role_template(
    role_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("agents:read")
    return ok(request, ctx.services.role_templates.get(role_id))


@router.patch("/role-templates/{role_id}", response_model=Envelope[RoleTemplateOut])
def update_role_template(
    role_id: str,
    payload: RoleTemplateUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.role_templates.update(ctx.actor, role_id, payload))


@router.post(
    "/role-templates/{role_id}/duplicate",
    response_model=Envelope[RoleTemplateOut],
    status_code=201,
)
def duplicate_role_template(
    role_id: str,
    payload: RoleTemplateDuplicate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.role_templates.duplicate(ctx.actor, role_id, payload))


@router.post(
    "/role-templates/{role_id}/restore-defaults",
    response_model=Envelope[RoleTemplateOut],
)
def restore_role_template(
    role_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.role_templates.restore_defaults(ctx.actor, role_id))


@router.delete("/role-templates/{role_id}", response_model=Envelope[dict])
def delete_role_template(
    role_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.role_templates.delete(ctx.actor, role_id)
    return ok(request, {"id": role_id, "deleted": True})


@router.get("/agents", response_model=Envelope[list[AgentOut]])
def list_agents(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    q: Annotated[str | None, Query(max_length=200)] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> dict:
    ctx.actor.require("agents:read")
    return ok(request, ctx.services.agent.list(q=q, enabled=enabled))


@router.get("/agents/directory", response_model=Envelope[list[AgentDirectoryEntry]])
def agent_directory(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    """Enabled agents with only id, name and role; used by mention autocomplete."""
    ctx.actor.require("agents:read")
    return ok(request, ctx.services.agent.directory())


@router.post("/agents", response_model=Envelope[AgentOut], status_code=201)
def create_agent(
    payload: AgentCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.agent.create(ctx.actor, payload))


@router.get("/agents/{agent_id}", response_model=Envelope[AgentOut])
def get_agent(
    agent_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.actor.require("agents:read")
    return ok(request, ctx.services.agent.get(agent_id))


@router.patch("/agents/{agent_id}", response_model=Envelope[AgentOut])
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.agent.update(ctx.actor, agent_id, payload))


@router.post("/agents/{agent_id}/duplicate", response_model=Envelope[AgentOut], status_code=201)
def duplicate_agent(
    agent_id: str,
    payload: AgentDuplicate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.agent.duplicate(ctx.actor, agent_id, payload))


@router.post("/agents/test", response_model=Envelope[AgentTestResult])
def probe_agent(
    payload: AgentTestRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    """Test a connection before the agent is saved; nothing is written."""
    return ok(request, ctx.services.agent.probe(ctx.actor, payload))


@router.post("/agents/{agent_id}/test", response_model=Envelope[AgentTestResult])
def test_agent(
    agent_id: str,
    payload: AgentTestRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.agent.test(ctx.actor, agent_id, payload))


@router.delete("/agents/{agent_id}", response_model=Envelope[dict])
def delete_agent(
    agent_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    ctx.services.agent.delete(ctx.actor, agent_id)
    return ok(request, {"id": agent_id, "deleted": True})


__all__ = ["router"]
