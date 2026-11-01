from __future__ import annotations

from typing import Any

from fastapi import Request


def request_id(request: Request | None) -> str:
    if request is None:
        return ""
    return getattr(request.state, "request_id", "")


def envelope(data: Any, request: Request | None = None, meta: dict[str, Any] | None = None) -> dict:
    body: dict[str, Any] = {"success": True, "data": data, "request_id": request_id(request)}
    if meta is not None:
        body["meta"] = meta
    return body


def page_meta(total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}
