from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Envelope[T](BaseModel):
    """Uniform success envelope. Agents can rely on `success`, `data` and `request_id`."""

    success: bool = True
    data: T
    request_id: str
    meta: dict[str, Any] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str
