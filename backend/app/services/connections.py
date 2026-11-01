"""Endpoint validation and connection probes for agent providers.

Self-hosted deployments legitimately point at ``http://localhost:8080`` (llama.cpp, vLLM), so
private targets are allowed when explicitly enabled. Cloud metadata and link-local targets are
always rejected, redirects are never followed, and URLs carrying credentials are refused.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from ..core.errors import ValidationFailure

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "169.254.169.254",
        "fd00:ec2::254",
    }
)


def _is_blocked_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _resolves_to_blocked_address(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        address = info[4][0]
        try:
            if _is_blocked_ip(address):
                return True
        except ValueError:
            continue
    return False


def validate_endpoint(url: str, *, allow_private: bool) -> str:
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
    if hostname in BLOCKED_HOSTNAMES:
        raise ValidationFailure("Endpoint host is not allowed", details={"host": hostname})
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        if _is_blocked_ip(str(address)):
            raise ValidationFailure("Endpoint address is not allowed", details={"host": hostname})
        if not allow_private and (address.is_private or address.is_loopback):
            raise ValidationFailure(
                "Private network endpoints are disabled",
                details={"host": hostname},
            )
    elif _resolves_to_blocked_address(hostname):
        raise ValidationFailure("Endpoint host is not allowed", details={"host": hostname})
    return candidate.rstrip("/")


def _request(url: str, *, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload


def probe_openai_compatible(
    base_url: str, *, api_key: str | None, timeout: float
) -> dict[str, Any]:
    """Probe ``GET {base}/models``; the endpoint list is the cheapest liveness signal."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        status, payload = _request(f"{base_url}/models", headers=headers, timeout=timeout)
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
            for entry in data:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    models.append(entry["id"])
    return {
        "ok": True,
        "status": "connected",
        "message": f"Connected; {len(models)} model(s) reported",
        "latency_ms": latency,
        "models": models[:50],
    }


def probe_a2a(base_url: str, *, api_key: str | None, timeout: float) -> dict[str, Any]:
    """Fetch the agent card. A JSON body with a name is treated as a valid A2A agent."""
    url = base_url if base_url.endswith(".json") else f"{base_url}/.well-known/agent.json"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    try:
        status, payload = _request(url, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
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
