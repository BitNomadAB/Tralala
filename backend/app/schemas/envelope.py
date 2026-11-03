from __future__ import annotations

from pydantic import BaseModel

# The data of an envelope whose object the schema leaves open: any JSON object. It is the bare class
# on purpose: pydantic names a parametrised model after its argument, so ``Envelope[OpenObject]`` is
# the ``Envelope[dict]`` component of the OpenAPI document, where ``dict[str, object]`` would rename
# it. A route that returns one is annotated with the envelope it builds, ``dict[str, object]``.
OpenObject = dict


class Envelope[T](BaseModel):
    """Uniform success envelope. Agents can rely on `success`, `data` and `request_id`."""

    success: bool = True
    data: T
    request_id: str
    meta: dict[str, object] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: object | None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorBody
    request_id: str
