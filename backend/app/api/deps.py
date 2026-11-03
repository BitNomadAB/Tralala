from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, TypedDict

from fastapi import Header, Query, Request

from ..core.context import ActorContext
from ..core.errors import Forbidden, Unauthorized
from ..core.responses import envelope, page_meta
from ..core.security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, csrf_satisfied
from ..services import Services


@dataclass(slots=True)
class RequestContext:
    services: Services
    actor: ActorContext


def get_services(request: Request) -> Services:
    return request.app.state.services


def _resolve_actor(request: Request, services: Services) -> tuple[ActorContext, bool]:
    """Return (actor, cookie_authenticated)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
        return services.auth.actor_from_token(token), False
    session = request.cookies.get(SESSION_COOKIE)
    if session:
        return services.auth.actor_from_session(session), True
    raise Unauthorized("Authentication required")


def get_context(request: Request) -> RequestContext:
    services = get_services(request)
    actor, cookie_auth = _resolve_actor(request, services)
    if cookie_auth and not csrf_satisfied(
        request.method,
        request.headers.get(CSRF_HEADER, ""),
        request.cookies.get(CSRF_COOKIE, ""),
    ):
        raise Forbidden("CSRF token missing or invalid", code="csrf_failed")
    actor.request_id = getattr(request.state, "request_id", "")
    request.state.actor_id = actor.actor_id
    request.app.state.rate_limiter.check(actor.actor_id)
    return RequestContext(services=services, actor=actor)


def idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 200:
        raise Unauthorized("Invalid idempotency key", code="invalid_idempotency_key")
    return cleaned


@dataclass(slots=True)
class Pagination:
    limit: int
    offset: int

    @property
    def meta(self) -> dict[str, int | bool]:
        return page_meta(0, self.limit, self.offset)


def pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def ok(
    request: Request, data: object, meta: Mapping[str, object] | None = None
) -> dict[str, object]:
    return envelope(data, request, meta)


class PageResult(TypedDict):
    """One page of a listing: its items and where they sit in the whole."""

    items: object
    total: int
    limit: int
    offset: int


def page(request: Request, result: PageResult) -> dict[str, object]:
    return envelope(
        result["items"],
        request,
        page_meta(result["total"], result["limit"], result["offset"]),
    )


__all__ = [
    "PageResult",
    "Pagination",
    "RequestContext",
    "get_context",
    "get_services",
    "idempotency_key",
    "ok",
    "page",
    "pagination",
]
