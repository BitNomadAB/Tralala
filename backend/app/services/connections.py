"""Endpoint validation, the pinned client for agent endpoints, and connection probes.

Self-hosted deployments legitimately point at ``http://localhost:8080`` (llama.cpp, vLLM), so
private targets are allowed when explicitly enabled. Cloud metadata and link-local targets are
always rejected, redirects are never followed, and URLs carrying credentials are refused.

The address rule follows the OWASP SSRF prevention cheat sheet: a literal address and every address
a host name resolves to are classified by one function (``address_refusal``), and a single refused
address refuses the endpoint. The rule is applied when an endpoint is saved (``validate_endpoint``)
and again when a connection is made (``PinnedTransport``), which connects to the address it checked
and to nothing else, so a name that answers differently later (DNS rebinding) reaches nothing the
rule refuses.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit

import httpx

from ..core.errors import ValidationFailure

logger = logging.getLogger("tralala.connections")

# Every address a host name resolves to, in preference order; raises ``OSError`` when it does not.
type Resolver = Callable[[str], Sequence[str]]
type Refusal = Literal["forbidden", "private"]
type Address = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES = frozenset({"http", "https"})
# Cloud metadata services by name; METADATA_ADDRESSES catches every spelling of their addresses.
BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal", "metadata.goog", "instance-data"})
METADATA_ADDRESSES = frozenset(
    {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}
)


class EndpointProbe(TypedDict):
    """What a probe of an endpoint's model list or agent card found."""

    ok: bool
    status: str
    message: str
    latency_ms: int
    models: list[str]


class CompletionProbe(TypedDict):
    """What the smallest real chat completion found."""

    ok: bool
    status: str
    message: str
    latency_ms: int


class ForbiddenAddressError(httpx.ConnectError):
    """A connection was about to be made to an address the endpoint rule refuses."""


def resolve_host(host: str) -> list[str]:
    """The system resolver's addresses for ``host``, in its order and without repeats."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _literal_address(host: str) -> Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def address_refusal(value: str, *, allow_private: bool) -> Refusal | None:
    """Why a connection to the address ``value`` is refused, or ``None`` when it may be made.

    ``forbidden`` is never reachable: cloud metadata, link-local, multicast, unspecified and
    reserved addresses, and text that is not an address. ``private`` is reachable only when private
    endpoints are allowed: loopback (``127.0.0.0/8`` and ``::1`` alike), the private ranges and
    every other address that is not globally routable. An IPv4-mapped IPv6 address is judged as the
    IPv4 address it carries.
    """
    address = _literal_address(value)
    if address is None:
        return "forbidden"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_loopback:
        # Ahead of the reserved check: Python files ``::1`` under the reserved ``::/8``.
        return None if allow_private else "private"
    if (
        address in METADATA_ADDRESSES
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return "forbidden"
    if address.is_global or allow_private:
        return None
    return "private"


def _refused(refusal: Refusal, host: str, *, literal: bool) -> ValidationFailure:
    if refusal == "private":
        return ValidationFailure("Private network endpoints are disabled", details={"host": host})
    what = "address" if literal else "host"
    return ValidationFailure(f"Endpoint {what} is not allowed", details={"host": host})


def validate_endpoint(url: str, *, allow_private: bool, resolve: Resolver = resolve_host) -> str:
    """The endpoint URL without its trailing slash, or a ``ValidationFailure`` naming the host.

    A host name is resolved and every address it resolves to is held to ``address_refusal``. A name
    that does not resolve yet is accepted: the endpoint may be saved before its server is up, and
    ``PinnedTransport`` checks the connection itself when it is made.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ValidationFailure("Endpoint URL is required")
    parts = urlsplit(candidate)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValidationFailure(
            "Endpoint must use http or https",
            details={"allowed": sorted(ALLOWED_SCHEMES)},
        )
    if parts.username or parts.password:
        raise ValidationFailure("Endpoint must not embed credentials")
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise ValidationFailure("Endpoint must include a host")
    if hostname.rstrip(".") in BLOCKED_HOSTNAMES:
        raise ValidationFailure("Endpoint host is not allowed", details={"host": hostname})
    if _literal_address(hostname) is not None:
        refusal = address_refusal(hostname, allow_private=allow_private)
        if refusal is not None:
            raise _refused(refusal, hostname, literal=True)
        return candidate.rstrip("/")
    try:
        addresses: Sequence[str] = resolve(hostname)
    except OSError:
        addresses = ()
    refusals = {address_refusal(address, allow_private=allow_private) for address in addresses}
    if "forbidden" in refusals:
        raise _refused("forbidden", hostname, literal=False)
    if "private" in refusals:
        raise _refused("private", hostname, literal=False)
    return candidate.rstrip("/")


class PinnedTransport(httpx.BaseTransport):
    """Resolve once, check every address, then send the request to a checked address only.

    A check made when the endpoint was saved, or a moment before connecting, leaves a window in
    which DNS can answer differently (DNS rebinding). Here the request's own host is resolved, every
    address is held to ``address_refusal`` (one refused address refuses the request) and the
    request is sent to a checked address itself, so the socket cannot reach anything else. The Host
    header keeps the name, and for https the ``sni_hostname`` request extension makes TLS send and
    verify the name, exactly as if the name had been connected to. Each host name gets its own
    connection pool, so a TLS connection opened for one name is never reused for another name that
    shares its address. Checked addresses are tried in resolver order, as
    ``socket.create_connection`` does. The check reads the host httpx itself connects to, so a URL
    that two parsers read differently cannot slip past it.
    """

    def __init__(
        self,
        *,
        allow_private: bool,
        resolve: Resolver = resolve_host,
        connect: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport,
    ) -> None:
        self._allow_private = allow_private
        self._resolve = resolve
        self._connect = connect
        self._pools: dict[str, httpx.BaseTransport] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.raw_host.decode("ascii").lower()
        *fallbacks, last = self._checked_addresses(host, request)
        pool = self._pools.get(host)
        if pool is None:
            pool = self._pools[host] = self._connect()
        for address in fallbacks:
            try:
                return pool.handle_request(_pinned(request, host, address))
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
        return pool.handle_request(_pinned(request, host, last))

    def close(self) -> None:
        for pool in self._pools.values():
            pool.close()
        self._pools.clear()

    def _checked_addresses(self, host: str, request: httpx.Request) -> list[str]:
        if host.rstrip(".") in BLOCKED_HOSTNAMES:
            raise _forbidden(host, [], request)
        if _literal_address(host) is not None:
            addresses = [host]
        else:
            try:
                addresses = list(dict.fromkeys(self._resolve(host)))
            except OSError as exc:
                raise httpx.ConnectError(f"{host} does not resolve", request=request) from exc
            if not addresses:
                raise httpx.ConnectError(f"{host} does not resolve", request=request)
        refused = [
            address
            for address in addresses
            if address_refusal(address, allow_private=self._allow_private) is not None
        ]
        if refused:
            raise _forbidden(host, refused, request)
        return addresses


def _forbidden(host: str, addresses: list[str], request: httpx.Request) -> ForbiddenAddressError:
    # A saved endpoint passed the same rule, so this is usually a name that changed its answer.
    logger.warning(
        json.dumps({"event": "endpoint_address_refused", "host": host, "addresses": addresses})
    )
    return ForbiddenAddressError(f"{host} is not an allowed endpoint address", request=request)


def _pinned(request: httpx.Request, host: str, address: str) -> httpx.Request:
    """``request`` sent to ``address``, still naming ``host`` in Host and, for https, in TLS."""
    extensions = dict(request.extensions)
    if request.url.scheme == "https" and _literal_address(host) is None:
        extensions["sni_hostname"] = host
    return httpx.Request(
        request.method,
        request.url.copy_with(host=address),
        headers=request.headers,
        stream=request.stream,
        extensions=extensions,
    )


def endpoint_client(
    *,
    timeout: float,
    allow_private: bool,
    resolve: Resolver = resolve_host,
    connect: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport,
) -> httpx.Client:
    """The HTTP client for an agent endpoint: every connection pinned and checked, no redirects.

    Proxy environment variables do not apply to it: the address rule has to see the address that is
    connected to, and behind a proxy the proxy would choose it.
    """
    return httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        transport=PinnedTransport(allow_private=allow_private, resolve=resolve, connect=connect),
    )


def _request(
    url: str, *, headers: dict[str, str], timeout: float, allow_private: bool
) -> tuple[int, Any]:
    with endpoint_client(timeout=timeout, allow_private=allow_private) as client:
        response = client.get(url, headers=headers)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload


def probe_openai_compatible(
    base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
) -> EndpointProbe:
    """Probe ``GET {base}/models``; the endpoint list is the cheapest liveness signal."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        status, payload = _request(
            f"{base_url}/models", headers=headers, timeout=timeout, allow_private=allow_private
        )
    except Exception as exc:  # noqa: BLE001 - network failures are reported, not raised
        return {
            "ok": False,
            "status": "unreachable",
            "message": f"Could not reach the endpoint ({type(exc).__name__})",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models": [],
        }
    latency = int((time.monotonic() - started) * 1000)
    if status in (401, 403):
        return {
            "ok": False,
            "status": "unauthorized",
            "message": f"Endpoint rejected the credentials (HTTP {status})",
            "latency_ms": latency,
            "models": [],
        }
    if status >= 400:
        return {
            "ok": False,
            "status": f"http_{status}",
            "message": f"Endpoint answered HTTP {status}",
            "latency_ms": latency,
            "models": [],
        }
    models: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            models.extend(
                entry["id"]
                for entry in data
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            )
    return {
        "ok": True,
        "status": "connected",
        "message": f"Connected; {len(models)} model(s) reported",
        "latency_ms": latency,
        "models": models[:50],
    }


def probe_completion(
    base_url: str, *, model: str, api_key: str | None, timeout: float, allow_private: bool
) -> CompletionProbe:
    """Send the smallest real chat completion, to prove the model call actually works.

    Listing models shows the endpoint answers; it says nothing about whether the model name exists
    or whether the parameters Tralala sends are accepted. That gap is exactly a green test next to a
    generation that fails with ``HTTP 400``, so the answer is one tiny request that costs a handful
    of tokens. The provider's own sentence is carried through when it refuses.
    """
    from .runtime import provider_error

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer with the single word: ok"},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 16,
        "temperature": 0,
    }
    started = time.monotonic()
    try:
        with endpoint_client(timeout=timeout, allow_private=allow_private) as client:
            response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001 - network failures are reported, not raised
        return {
            "ok": False,
            "status": "unreachable",
            "message": f"The model call did not reach the endpoint ({type(exc).__name__})",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    latency = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        return {
            "ok": False,
            "status": f"http_{response.status_code}",
            "message": f"The model call was refused: {provider_error(response)}",
            "latency_ms": latency,
        }
    try:
        answer = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return {
            "ok": False,
            "status": "malformed_response",
            "message": "The model call answered, but not with a chat completion",
            "latency_ms": latency,
        }
    preview = " ".join(str(answer or "").split())[:60]
    return {
        "ok": True,
        "status": "completed",
        "message": f"Model {model} answered" + (f": {preview}" if preview else ""),
        "latency_ms": latency,
    }


def probe_a2a(
    base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
) -> EndpointProbe:
    """Fetch the agent card. A JSON body with a name is treated as a valid A2A agent."""
    url = base_url if base_url.endswith(".json") else f"{base_url}/.well-known/agent.json"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        status, payload = _request(
            url, headers=headers, timeout=timeout, allow_private=allow_private
        )
    except Exception as exc:  # noqa: BLE001 - network failures are reported, not raised
        return {
            "ok": False,
            "status": "unreachable",
            "message": f"Could not reach the agent card ({type(exc).__name__})",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "models": [],
        }
    latency = int((time.monotonic() - started) * 1000)
    if status in (401, 403):
        return {
            "ok": False,
            "status": "unauthorized",
            "message": f"Agent card requires authorization (HTTP {status})",
            "latency_ms": latency,
            "models": [],
        }
    if status >= 400 or not isinstance(payload, dict) or not payload.get("name"):
        return {
            "ok": False,
            "status": f"http_{status}",
            "message": "Response is not an A2A agent card",
            "latency_ms": latency,
            "models": [],
        }
    skills = payload.get("skills")
    names = [
        entry.get("name")
        for entry in skills
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    ] if isinstance(skills, list) else []
    return {
        "ok": True,
        "status": "connected",
        "message": f"Agent card found for {payload.get('name')}",
        "latency_ms": latency,
        "models": names[:50],
    }
