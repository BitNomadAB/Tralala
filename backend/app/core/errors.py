from __future__ import annotations

from collections.abc import Mapping


class ApiError(Exception):
    """Structured application error rendered as a machine-readable envelope."""

    status_code = 400
    code = "bad_request"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Mapping[str, object] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        self.details = details


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"


class Forbidden(ApiError):
    status_code = 403
    code = "forbidden"


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


class VersionConflict(Conflict):
    code = "version_conflict"


class ValidationFailure(ApiError):
    status_code = 422
    code = "validation_failed"


class PayloadTooLarge(ApiError):
    status_code = 413
    code = "payload_too_large"


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"
    retryable = True


class ServiceUnavailable(ApiError):
    status_code = 503
    code = "unavailable"
    retryable = True
