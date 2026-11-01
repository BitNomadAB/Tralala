"""Timestamp parsing shared by request schemas and filters.

Due dates are stored as ISO 8601 UTC strings. Accepting free text silently breaks overdue
queries and due-date ordering, so invalid values are rejected at the boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .errors import ValidationFailure


def normalize_timestamp(value: str | None) -> str | None:
    """Return a normalized UTC timestamp, or raise ValueError for invalid input."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    candidate = f"{text}T00:00:00+00:00" if len(text) == 10 and text[4] == "-" else text
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("must be an ISO 8601 date or timestamp") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_due_filter(value: str | None) -> str | None:
    """Filter variant that reports a structured 422 instead of a validation error."""
    try:
        return normalize_timestamp(value)
    except ValueError as exc:
        raise ValidationFailure(
            "due_before must be an ISO 8601 date or timestamp",
            details={"due_before": value},
        ) from exc
