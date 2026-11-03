from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request


def request_id(request: Request | None) -> str:
    if request is None:
        return ""
    return getattr(request.state, "request_id", "")


def envelope(
    data: object, request: Request | None = None, meta: Mapping[str, object] | None = None
) -> dict[str, object]:
    body: dict[str, object] = {"success": True, "data": data, "request_id": request_id(request)}
    if meta is not None:
        body["meta"] = meta
    return body


def page_meta(total: int, limit: int, offset: int) -> dict[str, int | bool]:
    return {"total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}
