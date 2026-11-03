from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from ...core.errors import Unauthorized, ValidationFailure
from ...core.security import CSRF_COOKIE, SESSION_COOKIE
from ...schemas.auth import (
    ActorOut,
    CredentialCreate,
    CredentialCreated,
    CredentialOut,
    EnrolRequest,
    LoginRequest,
    LoginResponse,
    PasswordChange,
    PreferencesOut,
    PreferencesUpdate,
)
from ...schemas.envelope import Envelope
from ..deps import RequestContext, get_context, ok

router = APIRouter(tags=["auth"])


def client_address(request: Request) -> str:
    """Client address for throttling; trusts X-Forwarded-For only when configured."""
    settings = request.app.state.settings
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


@router.post("/auth/login", response_model=Envelope[LoginResponse])
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    services = request.app.state.services
    address = client_address(request)
    throttle = request.app.state.login_throttle
    user_key = f"user:{payload.username.strip().casefold()}"
    ip_key = f"ip:{address}"
    request.app.state.rate_limiter.check(f"login:{address}")
    # Sign-ins run in parallel, so the attempt counts from here rather than from its failure.
    with throttle.attempt(user_key, ip_key):
        try:
            result = services.auth.login(payload.username, payload.password)
        except Unauthorized:
            throttle.record_failure(user_key, ip_key)
            raise
        throttle.reset(user_key)
    max_age = services.settings.session_ttl_seconds
    response.set_cookie(
        SESSION_COOKIE,
        result["session"],
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=services.settings.cookie_secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        result["csrf_token"],
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=services.settings.cookie_secure,
        path="/",
    )
    return ok(
        request,
        {"actor": result["actor"], "csrf_token": result["csrf_token"]},
    )


@router.post("/auth/enrol", response_model=Envelope[LoginResponse])
def enrol(payload: EnrolRequest, request: Request, response: Response) -> dict:
    """Use a one-time invitation link: set the password and start a session.

    Public by design (the person has no session yet), so it is throttled like login and answers with
    the same generic messages rather than revealing whether a link ever existed.
    """
    services = request.app.state.services
    address = client_address(request)
    throttle = request.app.state.login_throttle
    request.app.state.rate_limiter.check(f"enrol:{address}")
    token_key = f"invite:{address}"
    with throttle.attempt(token_key, f"enrol-ip:{address}"):
        try:
            result = services.auth.accept_invite(payload.token, payload.password)
        except (Unauthorized, ValidationFailure):
            throttle.record_failure(token_key, f"enrol-ip:{address}")
            raise
        throttle.reset(token_key)
    max_age = services.settings.session_ttl_seconds
    response.set_cookie(
        SESSION_COOKIE,
        result["session"],
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=services.settings.cookie_secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        result["csrf_token"],
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=services.settings.cookie_secure,
        path="/",
    )
    return ok(request, {"actor": result["actor"], "csrf_token": result["csrf_token"]})


@router.post("/auth/logout", response_model=Envelope[dict])
def logout(request: Request, response: Response) -> dict:
    services = request.app.state.services
    services.auth.logout(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return ok(request, {"logged_out": True})


@router.post("/auth/password", response_model=Envelope[dict])
def change_password(
    payload: PasswordChange,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    response: Response,
) -> dict:
    result = ctx.services.auth.change_password(
        ctx.actor, payload.current_password, payload.new_password
    )
    # Every session, including this one, was revoked: the client must sign in again.
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return ok(request, result)


@router.get("/auth/me", response_model=Envelope[ActorOut])
def me(ctx: Annotated[RequestContext, Depends(get_context)], request: Request) -> dict:
    actor = ctx.actor
    return ok(
        request,
        {
            "id": actor.actor_id,
            "type": actor.actor_type,
            "name": actor.actor_name,
            "role": actor.role,
            "scopes": sorted(actor.scopes),
            "preferences": ctx.services.auth.preferences(actor),
        },
    )


@router.get("/auth/preferences", response_model=Envelope[PreferencesOut])
def read_preferences(
    ctx: Annotated[RequestContext, Depends(get_context)], request: Request
) -> dict:
    return ok(request, ctx.services.auth.preferences(ctx.actor))


@router.put("/auth/preferences", response_model=Envelope[PreferencesOut])
def write_preferences(
    payload: PreferencesUpdate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.auth.update_preferences(ctx.actor, payload))


@router.get("/auth/scopes", response_model=Envelope[list[str]])
def scopes(ctx: Annotated[RequestContext, Depends(get_context)], request: Request) -> dict:
    return ok(request, sorted(ctx.actor.scopes))


@router.get("/credentials", response_model=Envelope[list[CredentialOut]])
def list_credentials(
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
    owner_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    """Your own agent access; an administrator may list everybody's, optionally for one person."""
    return ok(request, ctx.services.auth.list_credentials(ctx.actor, owner_id=owner_id))


@router.post("/credentials", response_model=Envelope[CredentialCreated], status_code=201)
def create_credential(
    payload: CredentialCreate,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.auth.create_credential(ctx.actor, payload))


@router.post(
    "/credentials/{credential_id}/rotate",
    response_model=Envelope[CredentialCreated],
    status_code=201,
)
def rotate_credential(
    credential_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    return ok(request, ctx.services.auth.rotate_credential(ctx.actor, credential_id))


@router.post("/credentials/{credential_id}/revoke", response_model=Envelope[dict])
def revoke_credential(
    credential_id: str,
    ctx: Annotated[RequestContext, Depends(get_context)],
    request: Request,
) -> dict:
    revoked = ctx.services.auth.revoke_credential(ctx.actor, credential_id)
    if not revoked:
        raise Unauthorized("Credential not found or already revoked")
    return ok(request, {"id": credential_id, "revoked": True})


@router.get("/credentials/mine", response_model=Envelope[list[CredentialOut]])
def list_my_credentials(
    ctx: Annotated[RequestContext, Depends(get_context)], request: Request
) -> dict:
    """Explicit alias for a person's own agent access, whatever their role."""
    owner = ctx.actor.actor_id
    return ok(request, ctx.services.auth.list_credentials(ctx.actor, owner_id=owner))


__all__ = ["router"]
