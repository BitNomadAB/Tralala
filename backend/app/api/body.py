"""Bounded reading of request bodies.

`Content-Length` is optional: a chunked request sends no header, so a middleware that only compares
the declared size has nothing to compare and lets the body through. Every endpoint that reads raw
bytes reads them here instead, where the limit is counted while the bytes arrive.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from ..core.errors import PayloadTooLarge


def _limit(request: Request) -> int:
    return int(request.app.state.services.settings.max_request_bytes)


async def read_limited_body(request: Request) -> bytes:
    limit = _limit(request)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise PayloadTooLarge(
            "Request body exceeds the configured limit", details={"max_bytes": limit}
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge(
                "Request body exceeds the configured limit", details={"max_bytes": limit}
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def read_limited_json(request: Request) -> Any:
    """The body as JSON, or a ``ValueError`` for the caller to turn into its own error."""
    body = await read_limited_body(request)
    return json.loads(body)
