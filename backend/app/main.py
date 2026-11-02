from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, get_args

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import mcp as mcp_routes
from .api.deps import get_context
from .api.v1 import agents as agent_routes
from .api.v1 import attachments as attachment_routes
from .api.v1 import auth as auth_routes
from .api.v1 import boards as board_routes
from .api.v1 import cards as card_routes
from .api.v1 import discussions as discussion_routes
from .api.v1 import history as history_routes
from .api.v1 import labels as label_routes
from .api.v1 import lists as list_routes
from .api.v1 import loops as loop_routes
from .api.v1 import repositories as repository_routes
from .api.v1 import search as search_routes
from .api.v1 import templates as template_routes
from .api.v1 import users as user_routes
from .core.config import Settings, get_settings
from .core.errors import ApiError
from .core.ratelimit import LoginThrottle, RateLimiter
from .services import Services
from .storage.sqlite import sqlite_supports_fts5

logger = logging.getLogger("tralala")

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _configure_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _error_response(
    request: Request, status_code: int, code: str, message: str, **extra: Any
) -> JSONResponse:
    body = {
        "success": False,
        "error": {"code": code, "message": message, "retryable": False, **extra},
        "request_id": getattr(request.state, "request_id", ""),
    }
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    _configure_logging()
    settings = settings or get_settings()
    app = FastAPI(
        title="Tralala API",
        version="1.0.0",
        description=(
            "REST interface for the Tralala application. Every operation exposed to "
            "the React UI and to WebMCP is available here. Responses use a stable envelope: "
            "`{success, data, request_id, meta}`; errors use `{success:false, error, request_id}`."
        ),
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.services = Services(settings)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.login_throttle = LoginThrottle()
    if not settings.cookie_secure:
        logger.warning(
            "TRALALA_COOKIE_SECURE is off; session cookies will be sent over plain HTTP. "
            "Enable it wherever the app is reachable over a network."
        )

    if settings.enable_docs:
        # Served locally so the schema and Swagger UI can require a session instead of being
        # publicly enumerable. Bearer-only agents can fetch /openapi.json with their token.
        @app.get("/openapi.json", include_in_schema=False)
        async def openapi_schema(request: Request) -> JSONResponse:
            if settings.docs_require_auth:
                get_context(request)
            return JSONResponse(app.openapi())

        @app.get("/docs", include_in_schema=False)
        async def swagger_docs(request: Request) -> HTMLResponse:
            if settings.docs_require_auth:
                get_context(request)
            return get_swagger_ui_html(
                openapi_url="/openapi.json", title=f"{app.title} - API documentation"
            )

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-CSRF-Token"],
            expose_headers=["X-Request-ID"],
        )

    @app.middleware("http")
    async def observability(request: Request, call_next):  # noqa: ANN001, ANN202
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = (
            incoming if REQUEST_ID_PATTERN.match(incoming) else str(uuid.uuid4())
        )
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > settings.max_request_bytes:
                return _error_response(
                    request, 413, "payload_too_large", "Request body exceeds the configured limit"
                )
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/") or request.url.path == "/mcp":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "actor_id": getattr(request.state, "actor_id", None),
                    "replayed": getattr(request.state, "replayed", False),
                }
            )
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        return _error_response(
            request, 422, "validation_failed", "Request validation failed", details=details
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            request,
            exc.status_code,
            f"http_{exc.status_code}",
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # The type is enough to triage; messages and tracebacks can carry SQL values.
        logger.error(
            json.dumps(
                {
                    "event": "unhandled_exception",
                    "request_id": getattr(request.state, "request_id", ""),
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                }
            )
        )
        return _error_response(
            request, 500, "internal_error", "An unexpected error occurred", retryable=True
        )

    @app.get("/api/v1/health", tags=["system"])
    async def health() -> dict:
        return {"success": True, "data": {"status": "ok"}}

    @app.get("/api/v1/meta", tags=["system"])
    async def meta(request: Request) -> dict:
        ctx = get_context(request)
        from .core.context import MEMBER_TOKEN_SCOPES, SCOPES
        from .schemas.auth import Scope

        settings = request.app.state.settings
        return {
            "success": True,
            "data": {
                "api_version": "v1",
                "scopes": list(SCOPES),
                # The token schema is the only authority for what a token may hold, so the
                # Settings page reads the grantable subset from here instead of keeping a copy.
                "token_scopes": [str(scope) for scope in get_args(Scope)],
                # A member manages their own agent access inside this narrower vocabulary.
                "member_token_scopes": list(MEMBER_TOKEN_SCOPES),
                "member_token_limits": {
                    "live": settings.member_token_limit,
                    "default_days": settings.member_token_default_days,
                    "max_days": settings.member_token_max_days,
                },
                "can_issue_tokens": ctx.actor.is_user,
                "features": {
                    "webmcp": "client-side capability detection",
                    "fts5": sqlite_supports_fts5(),
                    "idempotency": True,
                    "optimistic_concurrency": True,
                },
                "migrations": request.app.state.services.migrations.status(),
            },
        }

    for router in (
        auth_routes.router,
        board_routes.router,
        loop_routes.router,
        history_routes.router,
        list_routes.router,
        card_routes.router,
        label_routes.router,
        label_routes.checklists,
        label_routes.comments,
        search_routes.router,
        template_routes.router,
        repository_routes.router,
        agent_routes.router,
        attachment_routes.router,
        discussion_routes.router,
        user_routes.router,
    ):
        app.include_router(router, prefix="/api/v1")
    # The worker surface sits at the origin, not under /api/v1: `/mcp` is where an MCP client
    # looks, and `/llms.txt` is the convention a URL-only agent tries first.
    app.include_router(mcp_routes.router)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app.state.services.initialize()
        purged = app.state.services.registry.purge_expired_sessions()
        logger.info(
            json.dumps(
                {
                    "event": "startup",
                    "data_dir": str(settings.data_dir),
                    "purged_sessions": purged,
                }
            )
        )
        try:
            yield
        finally:
            app.state.services.shutdown()
            logger.info(json.dumps({"event": "shutdown"}))

    app.router.lifespan_context = lifespan

    return app

