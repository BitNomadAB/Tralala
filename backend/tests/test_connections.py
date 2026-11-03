"""Provider endpoints: what an agent may be pointed at, decided without touching the network."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from app.core.errors import ValidationFailure
from app.services import connections
from app.services.connections import validate_endpoint

# What the stand-in resolver answers; any other name does not resolve.
RESOLVES_TO = {
    "api.example.com": ["93.184.215.14"],
    "rebind.example.com": ["93.184.215.14", "169.254.169.254"],
    "multicast.example.com": ["224.0.0.251"],
}


@pytest.fixture(autouse=True)
def resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    def getaddrinfo(host: str, *_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        if host not in RESOLVES_TO:
            raise socket.gaierror(socket.EAI_NONAME, "unknown host")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))
            for address in RESOLVES_TO[host]
        ]

    monkeypatch.setattr(connections.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "file:///etc/passwd",
        "ftp://api.example.com/v1",
        "javascript:alert(1)",
        "http:///v1",
        "http://user:pass@api.example.com/v1",
        "https://token@api.example.com/v1",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://METADATA.GOOGLE.INTERNAL/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00:ec2::254]/latest",
        "http://[fe80::1]/v1",
        "http://0.0.0.0:8080/v1",
        "http://224.0.0.1/v1",
        "http://rebind.example.com/v1",
        "http://multicast.example.com/v1",
    ],
)
@pytest.mark.parametrize("allow_private", [True, False])
def test_an_unsafe_endpoint_is_refused(url: str, allow_private: bool) -> None:
    with pytest.raises(ValidationFailure) as refused:
        validate_endpoint(url, allow_private=allow_private)
    assert refused.value.status_code == 422


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8080/v1", "http://192.168.1.20:11434", "http://10.0.0.5/v1"],
)
def test_a_private_address_is_allowed_only_when_enabled(url: str) -> None:
    assert validate_endpoint(url, allow_private=True) == url
    with pytest.raises(ValidationFailure, match="Private network"):
        validate_endpoint(url, allow_private=False)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example.com/v1/", "https://api.example.com/v1"),
        ("  https://api.example.com/v1  ", "https://api.example.com/v1"),
        ("http://api.example.com:8443/v1/models", "http://api.example.com:8443/v1/models"),
        ("http://host.docker.internal:8080/v1", "http://host.docker.internal:8080/v1"),
    ],
)
def test_a_safe_endpoint_is_returned_without_its_trailing_slash(url: str, expected: str) -> None:
    assert validate_endpoint(url, allow_private=False) == expected
    assert validate_endpoint(url, allow_private=False) == expected


def test_the_refusal_names_the_host_but_never_the_credentials() -> None:
    with pytest.raises(ValidationFailure) as refused:
        validate_endpoint("http://169.254.169.254/latest", allow_private=True)
    assert refused.value.details == {"host": "169.254.169.254"}
    with pytest.raises(ValidationFailure) as embedded:
        validate_endpoint("http://user:hunter2@api.example.com/v1", allow_private=True)
    assert "hunter2" not in str(embedded.value.message) + str(embedded.value.details)
