"""Provider endpoints: what an agent may be pointed at, and what a connection to it may reach.

Name resolution is a stand-in handed to the code under test, and the server behind the pinned
client is an ``httpx.MockTransport``, so no test touches DNS or opens a socket.
"""

from __future__ import annotations

import ast
import json
import socket
import ssl
from collections.abc import Callable, Iterator, Mapping
from functools import partial
from pathlib import Path

import httpx
import pytest

from app.core.errors import ValidationFailure
from app.services import connections
from app.services.connections import (
    ForbiddenAddressError,
    address_refusal,
    endpoint_client,
    resolve_host,
    validate_endpoint,
)

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"

# What the stand-in resolver answers; any other name does not resolve.
RESOLVES_TO = {
    "api.example.com": [PUBLIC_V4],
    "dual.example.com": [PUBLIC_V6, PUBLIC_V4],
    "rebind.example.com": [PUBLIC_V4, "169.254.169.254"],
    "multicast.example.com": ["224.0.0.251"],
    "metadata.example.com": ["169.254.169.254"],
    "metadata-v6.example.com": ["fd00:ec2::254"],
    "mapped-metadata.example.com": ["::ffff:169.254.169.254"],
    "lan.example.com": ["192.168.1.20"],
    "loopback.example.com": ["::1", "127.0.0.1"],
    "shared.example.com": ["100.64.0.1"],
    "mixed.example.com": [PUBLIC_V4, "10.0.0.5"],
    "host.docker.internal": ["192.168.65.254"],
}


def resolve(host: str) -> list[str]:
    if host not in RESOLVES_TO:
        raise socket.gaierror(socket.EAI_NONAME, "unknown host")
    return RESOLVES_TO[host]


def check(url: str, *, allow_private: bool) -> str:
    return validate_endpoint(url, allow_private=allow_private, resolve=resolve)


# --- the address rule ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "without_private", "with_private"),
    [
        (PUBLIC_V4, None, None),
        (PUBLIC_V6, None, None),
        ("127.0.0.1", "private", None),
        ("127.8.9.10", "private", None),
        ("::1", "private", None),
        ("::ffff:127.0.0.1", "private", None),
        ("10.0.0.5", "private", None),
        ("172.16.0.1", "private", None),
        ("192.168.1.20", "private", None),
        ("::ffff:10.0.0.5", "private", None),
        ("100.64.0.1", "private", None),
        ("fd12:3456::1", "private", None),
        ("169.254.169.254", "forbidden", "forbidden"),
        ("169.254.10.1", "forbidden", "forbidden"),
        ("::ffff:169.254.169.254", "forbidden", "forbidden"),
        ("fd00:ec2::254", "forbidden", "forbidden"),
        ("fe80::1", "forbidden", "forbidden"),
        ("fe80::1%12", "forbidden", "forbidden"),
        ("224.0.0.251", "forbidden", "forbidden"),
        ("ff02::1", "forbidden", "forbidden"),
        ("::", "forbidden", "forbidden"),
        ("240.0.0.1", "forbidden", "forbidden"),
        ("not-an-address", "forbidden", "forbidden"),
        ("", "forbidden", "forbidden"),
    ],
)
def test_every_address_is_judged_by_one_rule(
    address: str, without_private: str | None, with_private: str | None
) -> None:
    assert address_refusal(address, allow_private=False) == without_private
    assert address_refusal(address, allow_private=True) == with_private
    assert address_refusal(address, allow_private=True) == with_private


# What socket.getaddrinfo returns for each address.
type AddressInfo = tuple[
    socket.AddressFamily, socket.SocketKind, int, str, tuple[str, int] | tuple[str, int, int, int]
]


def test_the_system_resolver_keeps_its_order_and_drops_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def getaddrinfo(host: str, port: str | int | None, **_kwargs: object) -> list[AddressInfo]:
        assert (host, port) == ("api.example.com", None)
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (PUBLIC_V6, 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_V4, 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (PUBLIC_V6, 0, 0, 0)),
        ]

    monkeypatch.setattr(connections.socket, "getaddrinfo", getaddrinfo)
    assert resolve_host("api.example.com") == [PUBLIC_V6, PUBLIC_V4]


# --- validation when an endpoint is saved ----------------------------------------------------


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
        "http://metadata.google.internal./v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:169.254.169.254]/latest",
        "http://[fd00:ec2::254]/latest",
        "http://[fe80::1]/v1",
        "http://0.0.0.0:8080/v1",
        "http://[::]:8080/v1",
        "http://224.0.0.1/v1",
        "http://240.0.0.1/v1",
        "http://rebind.example.com/v1",
        "http://multicast.example.com/v1",
        "http://metadata.example.com/latest",
        "http://metadata-v6.example.com/latest",
        "http://mapped-metadata.example.com/latest",
    ],
)
@pytest.mark.parametrize("allow_private", [True, False])
def test_an_unsafe_endpoint_is_refused(url: str, allow_private: bool) -> None:
    with pytest.raises(ValidationFailure) as refused:
        check(url, allow_private=allow_private)
    assert refused.value.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
        "http://[::ffff:127.0.0.1]:8080/v1",
        "http://192.168.1.20:11434",
        "http://10.0.0.5/v1",
        "http://100.64.0.1/v1",
        "http://lan.example.com:11434",
        "http://loopback.example.com:8080/v1",
        "http://shared.example.com/v1",
        "http://mixed.example.com/v1",
        "http://host.docker.internal:8080/v1",
    ],
)
def test_a_private_address_or_name_is_allowed_only_when_enabled(url: str) -> None:
    assert check(url, allow_private=True) == url
    with pytest.raises(ValidationFailure, match="Private network"):
        check(url, allow_private=False)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example.com/v1/", "https://api.example.com/v1"),
        ("  https://api.example.com/v1  ", "https://api.example.com/v1"),
        ("http://api.example.com:8443/v1/models", "http://api.example.com:8443/v1/models"),
        ("https://dual.example.com/v1", "https://dual.example.com/v1"),
        (f"http://{PUBLIC_V4}:8080/v1", f"http://{PUBLIC_V4}:8080/v1"),
    ],
)
def test_a_public_endpoint_is_returned_without_its_trailing_slash(url: str, expected: str) -> None:
    assert check(url, allow_private=False) == expected
    assert check(url, allow_private=False) == expected


def test_a_name_that_does_not_resolve_yet_is_saved_and_checked_when_connected() -> None:
    url = "http://not-up-yet.example.com/v1"
    assert check(url, allow_private=False) == url
    upstream = Upstream()
    with client(upstream) as pinned, pytest.raises(httpx.ConnectError) as failed:
        pinned.get(url)
    assert not isinstance(failed.value, ForbiddenAddressError)
    assert upstream.requests == []


def test_the_refusal_names_the_host_but_never_an_address_or_the_credentials() -> None:
    with pytest.raises(ValidationFailure) as refused:
        check("http://169.254.169.254/latest", allow_private=True)
    assert refused.value.details == {"host": "169.254.169.254"}
    with pytest.raises(ValidationFailure) as resolved:
        check("http://lan.example.com/v1", allow_private=False)
    assert resolved.value.details == {"host": "lan.example.com"}
    with pytest.raises(ValidationFailure) as embedded:
        check("http://user:hunter2@api.example.com/v1", allow_private=True)
    assert "hunter2" not in str(embedded.value.message) + str(embedded.value.details)


# --- the pinned client: the check where the connection is made -------------------------------


def _empty_listing(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


class Upstream:
    """The servers behind the pinned client: records what reaches them and answers fixed text."""

    def __init__(
        self,
        answer: Callable[[httpx.Request], httpx.Response] | None = None,
        *,
        down: frozenset[str] = frozenset(),
    ) -> None:
        self.answer = answer or _empty_listing
        self.down = down
        self.requests: list[httpx.Request] = []
        self.pools: list[RecordingPool] = []

    def connect(self) -> httpx.BaseTransport:
        pool = RecordingPool(self.handle)
        self.pools.append(pool)
        return pool

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host in self.down:
            raise httpx.ConnectError("connection refused", request=request)
        return self.answer(request)


class RecordingPool(httpx.MockTransport):
    closed = False

    def close(self) -> None:
        self.closed = True


def client(
    upstream: Upstream,
    *,
    allow_private: bool = False,
    resolver: Callable[[str], list[str]] = resolve,
) -> httpx.Client:
    return endpoint_client(
        timeout=5, allow_private=allow_private, resolve=resolver, connect=upstream.connect
    )


def test_a_request_goes_to_the_checked_address_under_its_own_name() -> None:
    upstream = Upstream()
    with client(upstream) as pinned:
        response = pinned.post(
            "https://api.example.com:8443/v1/chat/completions?stream=false", json={"ping": 1}
        )
    assert response.status_code == 200
    assert str(response.request.url) == (
        "https://api.example.com:8443/v1/chat/completions?stream=false"
    )
    (sent,) = upstream.requests
    assert str(sent.url) == f"https://{PUBLIC_V4}:8443/v1/chat/completions?stream=false"
    assert sent.headers["host"] == "api.example.com:8443"
    assert sent.extensions["sni_hostname"] == "api.example.com"
    assert sent.content == b'{"ping":1}'
    assert "timeout" in sent.extensions


def test_plain_http_and_a_literal_address_need_no_tls_name() -> None:
    def no_lookup(host: str) -> list[str]:
        raise AssertionError(f"a literal address was resolved: {host}")

    upstream = Upstream()
    with client(upstream) as pinned:
        pinned.get("http://api.example.com/v1/models")
    with client(upstream, allow_private=True, resolver=no_lookup) as pinned:
        pinned.get("https://10.0.0.5/v1/models")
        pinned.get("http://[::1]:8080/v1/models")
    by_name, by_v4, by_v6 = upstream.requests
    assert "sni_hostname" not in by_name.extensions
    assert (str(by_v4.url), by_v4.headers["host"]) == ("https://10.0.0.5/v1/models", "10.0.0.5")
    assert "sni_hostname" not in by_v4.extensions
    assert str(by_v6.url) == "http://[::1]:8080/v1/models"


@pytest.mark.parametrize(
    ("moved_to", "allow_private"),
    [
        (["169.254.169.254"], True),
        (["169.254.169.254"], False),
        (["fd00:ec2::254"], True),
        (["::ffff:169.254.169.254"], True),
        ([PUBLIC_V4, "169.254.169.254"], True),
        (["10.0.0.5"], False),
        (["::1"], False),
    ],
)
def test_a_name_that_changes_its_answer_after_validation_is_refused_at_connect(
    moved_to: list[str], allow_private: bool
) -> None:
    answers: Iterator[list[str]] = iter([[PUBLIC_V4], moved_to])

    def rebinding(_host: str) -> list[str]:
        return next(answers)

    url = "http://rebinding.example.com/v1"
    assert validate_endpoint(url, allow_private=allow_private, resolve=rebinding) == url
    upstream = Upstream()
    with (
        client(upstream, allow_private=allow_private, resolver=rebinding) as pinned,
        pytest.raises(ForbiddenAddressError),
    ):
        pinned.get(f"{url}/models")
    assert upstream.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://rebind.example.com/v1",
        "http://metadata.example.com/latest",
        "http://metadata.google.internal/computeMetadata/v1",
        "http://169.254.169.254/latest",
        "http://[::ffff:169.254.169.254]/latest",
    ],
)
def test_a_refused_address_is_never_connected_even_with_private_endpoints_allowed(
    url: str,
) -> None:
    upstream = Upstream()
    with client(upstream, allow_private=True) as pinned, pytest.raises(ForbiddenAddressError):
        pinned.get(url)
    assert upstream.requests == []


def test_a_private_address_is_connected_only_when_allowed() -> None:
    upstream = Upstream()
    with client(upstream, allow_private=False) as pinned, pytest.raises(ForbiddenAddressError):
        pinned.get("http://lan.example.com:11434/v1/models")
    with client(upstream, allow_private=True) as pinned:
        assert pinned.get("http://lan.example.com:11434/v1/models").status_code == 200
    (sent,) = upstream.requests
    assert str(sent.url) == "http://192.168.1.20:11434/v1/models"


def test_an_address_that_cannot_be_reached_falls_back_to_the_next_checked_one() -> None:
    upstream = Upstream(down=frozenset({PUBLIC_V6}))
    with client(upstream) as pinned:
        assert pinned.get("https://dual.example.com/v1/models").status_code == 200
    assert [request.url.host for request in upstream.requests] == [PUBLIC_V6, PUBLIC_V4]
    assert {request.extensions["sni_hostname"] for request in upstream.requests} == {
        "dual.example.com"
    }


def test_when_every_checked_address_is_down_the_connect_error_surfaces() -> None:
    upstream = Upstream(down=frozenset({PUBLIC_V6, PUBLIC_V4}))
    with client(upstream) as pinned, pytest.raises(httpx.ConnectError) as failed:
        pinned.get("https://dual.example.com/v1/models")
    assert not isinstance(failed.value, ForbiddenAddressError)
    assert len(upstream.requests) == 2


def test_a_redirect_is_returned_and_never_followed() -> None:
    upstream = Upstream(
        lambda _request: httpx.Response(
            302, headers={"Location": "http://169.254.169.254/latest/meta-data"}
        )
    )
    with client(upstream) as pinned:
        response = pinned.get("http://api.example.com/v1/models")
    assert response.status_code == 302
    assert len(upstream.requests) == 1


def test_only_the_pinned_client_and_the_fixed_github_host_open_http_clients() -> None:
    app = Path(connections.__file__).resolve().parents[1]
    opened: set[str] = set()
    for source in app.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"Client", "AsyncClient"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "httpx"
            ):
                opened.add(source.relative_to(app).as_posix())
    # GitHub calls go to the fixed api.github.com; every agent endpoint goes through
    # connections.endpoint_client.
    assert opened == {
        "services/connections.py",
        "services/repositories.py",
        "services/repo_snapshot.py",
    }


def test_each_name_has_its_own_connection_pool_and_closing_closes_them() -> None:
    upstream = Upstream()
    with client(upstream) as pinned:
        pinned.get("https://api.example.com/v1/models")
        pinned.get("https://api.example.com/v1/models")
        pinned.get("https://dual.example.com/v1/models")
        assert len(upstream.pools) == 2
        assert not any(pool.closed for pool in upstream.pools)
    assert all(pool.closed for pool in upstream.pools)


# --- the probes use the pinned client --------------------------------------------------------

PROBES: dict[str, Callable[..., Mapping[str, object]]] = {
    "models": connections.probe_openai_compatible,
    "completion": partial(connections.probe_completion, model="example-model"),
    "agent card": connections.probe_a2a,
}


@pytest.fixture()
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    server = Upstream(
        lambda _request: httpx.Response(
            200,
            json={
                "data": [{"id": "example-model"}],
                "name": "Stub agent",
                "choices": [{"message": {"content": "ok"}}],
            },
        )
    )
    monkeypatch.setattr(
        connections,
        "endpoint_client",
        partial(endpoint_client, resolve=resolve, connect=server.connect),
    )
    return server


@pytest.mark.parametrize("probe", PROBES.values(), ids=PROBES.keys())
def test_a_probe_reaches_a_checked_endpoint(
    upstream: Upstream, probe: Callable[..., Mapping[str, object]]
) -> None:
    result = probe("https://api.example.com/v1", api_key=None, timeout=5, allow_private=False)
    assert result["ok"] is True
    # The model call is followed by the tool call; both go through the pinned client.
    assert len(upstream.requests) == (2 if probe is PROBES["completion"] else 1)
    for sent in upstream.requests:
        assert sent.url.host == PUBLIC_V4
        assert sent.headers["host"] == "api.example.com"


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _plain_http(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[SSL: WRONG_VERSION_NUMBER] wrong version number", request=request)


@pytest.mark.parametrize("probe", PROBES.values(), ids=PROBES.keys())
@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434/v1", "http://[::1]:11434/v1", "http://localhost:11434/v1"],
)
def test_a_loopback_endpoint_that_refuses_is_explained_as_the_container(
    upstream: Upstream, probe: Callable[..., Mapping[str, object]], url: str
) -> None:
    upstream.answer = _refused
    result = probe(url, api_key=None, timeout=5, allow_private=True)
    assert (result["ok"], result["status"]) == (False, "unreachable")
    assert str(result["message"]).endswith("(ConnectError). " + connections.CONTAINER_HINT)


@pytest.mark.parametrize("probe", PROBES.values(), ids=PROBES.keys())
def test_https_against_a_plain_http_endpoint_names_the_mismatch(
    upstream: Upstream, probe: Callable[..., Mapping[str, object]]
) -> None:
    upstream.answer = _plain_http
    result = probe("https://lan.example.com:8080/v1", api_key=None, timeout=5, allow_private=True)
    assert (result["ok"], result["status"]) == (False, "unreachable")
    assert str(result["message"]).endswith("(ConnectError). " + connections.PLAIN_HTTP_HINT)


def test_other_connection_failures_carry_no_hint() -> None:
    request = httpx.Request("GET", "https://lan.example.com/v1/models")
    untrusted = httpx.ConnectError("certificate verify failed", request=request)
    untrusted.__cause__ = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
    for url, exc in [
        ("http://lan.example.com/v1", httpx.ConnectError("refused", request=request)),
        ("https://lan.example.com/v1", untrusted),
        ("http://127.0.0.1/v1", connections.ForbiddenAddressError("refused", request=request)),
        ("http://127.0.0.1/v1", httpx.ReadError("reset", request=request)),
    ]:
        message = connections.unreachable("Could not reach the endpoint", url, exc)
        assert message == f"Could not reach the endpoint ({type(exc).__name__})"


@pytest.mark.parametrize("probe", PROBES.values(), ids=PROBES.keys())
@pytest.mark.parametrize(
    ("url", "allow_private"),
    [("http://metadata.example.com/v1", True), ("http://lan.example.com/v1", False)],
)
def test_a_probe_reports_a_refused_address_without_connecting(
    upstream: Upstream, probe: Callable[..., Mapping[str, object]], url: str, allow_private: bool
) -> None:
    result = probe(url, api_key=None, timeout=5, allow_private=allow_private)
    assert (result["ok"], result["status"]) == (False, "unreachable")
    assert "ForbiddenAddressError" in str(result["message"])
    assert upstream.requests == []


# --- the trial call asks for a JSON schema as the answer's format -------------------------------


def _chat(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def _answers(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """A server that answers every request with ``response``."""

    def answer(_request: httpx.Request) -> httpx.Response:
        return response

    return answer


def _sent(request: httpx.Request) -> dict[str, object]:
    """The JSON object a request carried."""
    body: dict[str, object] = json.loads(request.content)
    return body


def _trial() -> connections.CompletionProbe:
    return connections.probe_completion(
        "https://api.example.com/v1",
        model="example-model",
        api_key=None,
        timeout=5,
        allow_private=False,
    )


def test_a_model_that_answers_the_schema_call_takes_a_json_schema(upstream: Upstream) -> None:
    upstream.answer = _answers(_chat('{"answer": "ok"}'))
    result = _trial()
    assert (result["ok"], result["supports_json_schema"]) == (True, True)
    sent, _tool_call = upstream.requests
    assert _sent(sent)["response_format"] == connections.PROBE_RESPONSE_FORMAT


@pytest.mark.parametrize("status", [400, 422])
def test_a_provider_that_refuses_the_schema_is_tested_without_it(
    upstream: Upstream, status: int
) -> None:
    def refuse_the_format(request: httpx.Request) -> httpx.Response:
        if "response_format" in _sent(request):
            return httpx.Response(status, json={"error": {"message": "response_format unknown"}})
        return _chat("ok")

    upstream.answer = refuse_the_format
    result = _trial()
    assert result == {
        "ok": True,
        "status": "completed",
        "message": "Model example-model answered: ok",
        "latency_ms": result["latency_ms"],
        "supports_json_schema": False,
        "supports_tools": False,
    }
    first, second, _tool_call = (_sent(request) for request in upstream.requests)
    assert second == {key: value for key, value in first.items() if key != "response_format"}


def test_a_model_the_plain_call_cannot_reach_fails_the_test_with_its_own_refusal(
    upstream: Upstream,
) -> None:
    upstream.answer = _answers(httpx.Response(404, json={"error": {"message": "no such model"}}))
    result = _trial()
    assert (result["ok"], result["status"], result["supports_json_schema"]) == (
        False,
        "http_404",
        False,
    )
    assert result["message"] == "The model call was refused: HTTP 404: no such model"
    assert len(upstream.requests) == 2


def test_the_model_call_sends_no_temperature(upstream: Upstream) -> None:
    upstream.answer = _answers(_chat('{"answer": "ok"}'))
    _trial()
    sent, tool_call = upstream.requests
    assert ("temperature" in _sent(sent), _sent(sent)["max_tokens"]) == (False, 16)
    assert "temperature" not in _sent(tool_call)


def test_a_model_that_runs_out_of_time_names_the_tests_own_limit(upstream: Upstream) -> None:
    def too_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    upstream.answer = too_slow
    result = connections.probe_completion(
        "https://api.example.com/v1",
        model="example-model",
        api_key=None,
        timeout=30,
        allow_private=False,
    )
    assert (result["ok"], result["status"], result["supports_json_schema"]) == (
        False,
        "timeout",
        False,
    )
    assert result["message"] == (
        "The model did not answer within 30 s, the connection test's own limit; a generation "
        "waits as long as the agent's timeout allows"
    )


def test_a_server_error_is_reported_without_a_second_call(upstream: Upstream) -> None:
    upstream.answer = _answers(httpx.Response(503, text="busy"))
    result = _trial()
    assert (result["ok"], result["status"]) == (False, "http_503")
    assert len(upstream.requests) == 1


# --- one more call offers a dummy tool: a model that calls it takes tools -----------------------


def _offers_tools(request: httpx.Request) -> bool:
    return "tools" in _sent(request)


def _tool_answer(name: str) -> httpx.Response:
    call = {"id": "call_1", "type": "function", "function": {"name": name, "arguments": "{}"}}
    return httpx.Response(
        200, json={"choices": [{"message": {"content": None, "tool_calls": [call]}}]}
    )


def _with_tools(
    answer: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    """A server that answers the model call as before and the tool call with ``answer``."""

    def handle(request: httpx.Request) -> httpx.Response:
        return answer(request) if _offers_tools(request) else _chat('{"answer": "ok"}')

    return handle


def test_a_model_that_calls_the_dummy_tool_takes_tools(upstream: Upstream) -> None:
    upstream.answer = _with_tools(lambda _request: _tool_answer("report_ok"))
    result = _trial()
    assert (result["ok"], result["supports_json_schema"], result["supports_tools"]) == (
        True,
        True,
        True,
    )
    assert result["message"] == 'Model example-model answered: {"answer": "ok"}'
    plain, offer = upstream.requests
    assert not _offers_tools(plain)
    sent = _sent(offer)
    assert sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "report_ok",
                "description": "Report that the connection test reached you.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert (sent["model"], sent["tool_choice"], "response_format" in sent) == (
        "example-model",
        "auto",
        False,
    )
    assert "report_ok" in json.dumps(sent["messages"])


@pytest.mark.parametrize(
    "answer",
    [
        _chat("ok"),
        _tool_answer("something_else"),
        httpx.Response(400, json={"error": {"message": "does not support tools"}}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, text="not json"),
    ],
    ids=["text answer", "another tool", "refused", "no completion", "not JSON"],
)
def test_a_model_that_does_not_call_the_dummy_tool_takes_no_tools_and_still_passes(
    upstream: Upstream, answer: httpx.Response
) -> None:
    upstream.answer = _with_tools(_answers(answer))
    result = _trial()
    assert (result["ok"], result["status"], result["supports_tools"]) == (
        True,
        "completed",
        False,
    )
    assert len(upstream.requests) == 2


def test_a_tool_call_that_runs_out_of_time_takes_no_tools_and_still_passes(
    upstream: Upstream,
) -> None:
    def too_slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    upstream.answer = _with_tools(too_slow)
    result = _trial()
    assert (result["ok"], result["supports_tools"]) == (True, False)


def test_a_model_call_that_fails_offers_no_tools(upstream: Upstream) -> None:
    upstream.answer = _answers(httpx.Response(404, json={"error": "no such model"}))
    result = _trial()
    assert (result["ok"], result["supports_tools"]) == (False, False)
    assert not any(_offers_tools(request) for request in upstream.requests)
