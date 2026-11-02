from __future__ import annotations

from typing import Any

import httpx

from app.services.runtime import provider_error


class _Response:
    """The three attributes `provider_error` reads, without a network."""

    def __init__(self, status_code: int, body: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("not json")
        return self._body


def test_the_provider_sentence_travels_with_the_status() -> None:
    response = _Response(
        400, {"error": {"message": "Model Not Exist", "type": "invalid_request_error"}}
    )
    assert provider_error(response) == "HTTP 400: Model Not Exist"


def test_an_error_string_is_used_when_that_is_all_the_provider_sends() -> None:
    response = _Response(422, {"error": "temperature unsupported"})
    assert provider_error(response) == "HTTP 422: temperature unsupported"


def test_a_top_level_message_counts_too() -> None:
    assert provider_error(_Response(429, {"message": "Rate limit reached"})) == (
        "HTTP 429: Rate limit reached"
    )


def test_a_plain_text_body_is_squashed_onto_one_line() -> None:
    response = _Response(502, None, "upstream\nunavailable\n")
    assert provider_error(response) == "HTTP 502: upstream unavailable"


def test_a_long_body_is_bounded() -> None:
    response = _Response(400, {"error": {"message": "x" * 500}})
    message = provider_error(response)
    assert message.startswith("HTTP 400: ")
    assert len(message) <= len("HTTP 400: ") + 200


def test_an_empty_body_stays_the_status_alone() -> None:
    assert provider_error(_Response(500, None, "")) == "HTTP 500"


def test_the_error_never_carries_the_response_headers() -> None:
    response = _Response(401, {"error": {"message": "Incorrect API key provided"}})
    response.headers = httpx.Headers({"authorization": "Bearer secret-value"})  # type: ignore[attr-defined]
    assert "secret-value" not in provider_error(response)
