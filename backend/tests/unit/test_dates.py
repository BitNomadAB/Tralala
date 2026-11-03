"""Timestamps: ISO 8601 in, normalized UTC out, anything else refused at the boundary."""

from __future__ import annotations

import pytest

from app.core.dates import normalize_timestamp, parse_due_filter
from app.core.errors import ValidationFailure
from app.services.common import iso_utc, parse_timestamp


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2027-01-15", "2027-01-15T00:00:00Z"),
        (" 2027-01-15 ", "2027-01-15T00:00:00Z"),
        ("2027-01-15T10:30:00", "2027-01-15T10:30:00Z"),
        ("2027-01-15T10:30:00Z", "2027-01-15T10:30:00Z"),
        ("2027-01-15T10:30:00+02:00", "2027-01-15T08:30:00Z"),
        ("2027-01-15T00:30:00-01:00", "2027-01-15T01:30:00Z"),
        ("2027-01-15T10:30:00.987654Z", "2027-01-15T10:30:00Z"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_a_timestamp_is_normalized_to_utc(value: str | None, expected: str | None) -> None:
    assert normalize_timestamp(value) == expected
    assert normalize_timestamp(value) == expected


@pytest.mark.parametrize(
    "value", ["next tuesday", "2026-13-45", "15/01/2027", "2027-02-30", "2027-01-15T25:00:00"]
)
def test_free_text_is_not_a_timestamp(value: str) -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        normalize_timestamp(value)


def test_a_normalized_timestamp_stays_the_same() -> None:
    once = normalize_timestamp("2027-01-15T10:30:00+02:00")
    assert normalize_timestamp(once) == once


def test_a_due_filter_reports_a_structured_validation_error() -> None:
    with pytest.raises(ValidationFailure) as refused:
        parse_due_filter("soon")
    assert refused.value.status_code == 422
    assert refused.value.code == "validation_failed"
    assert refused.value.details == {"due_before": "soon"}


def test_a_valid_due_filter_passes_normalized() -> None:
    assert parse_due_filter("2027-01-15") == "2027-01-15T00:00:00Z"
    assert parse_due_filter(None) is None


def test_a_stored_timestamp_reads_back_as_the_same_text() -> None:
    moment = parse_timestamp("2027-01-15T10:30:00+02:00")
    assert moment is not None
    assert iso_utc(moment) == "2027-01-15T08:30:00Z"
    assert parse_timestamp("not a date") is None
    assert parse_timestamp(None) is None
