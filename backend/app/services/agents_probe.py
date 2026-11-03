"""Connection tests of agent profiles: the endpoint probe, then a model call when one is named.

The endpoint rule and the probes are passed in (``AgentEndpoints``; ``services.connections`` is the
real one), so a test runs without a network. ``services.agents`` calls ``probe_connection`` for a
stored agent and for a form that has not been saved, and re-exports the types.
"""

from __future__ import annotations

import logging
from typing import NotRequired, Protocol, TypedDict

from ..core.config import Settings
from ..core.errors import ValidationFailure
from ..core.secrets import CredentialError, open_secret
from ..db.generated.registry import AgentsRow
from ..schemas.agents import AgentTestRequest
from .connections import CompletionProbe, EndpointProbe

logger = logging.getLogger("tralala.agents")


class ProbeOutcome(TypedDict):
    """A connection test: the endpoint probe, plus the model call when a model was named.

    ``supports_json_schema`` is what the model call found (``connections.probe_completion``), and
    false when no model call was made or it failed.
    """

    ok: bool
    status: str
    message: str
    latency_ms: int
    models: list[str]
    supports_json_schema: bool
    completion: NotRequired[CompletionProbe]


class AgentEndpoints(Protocol):
    """The endpoint rule and the probes; ``services.connections`` is the real one."""

    def validate_endpoint(self, url: str, *, allow_private: bool) -> str: ...

    def probe_openai_compatible(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe: ...

    def probe_a2a(
        self, base_url: str, *, api_key: str | None, timeout: float, allow_private: bool
    ) -> EndpointProbe: ...

    def probe_completion(
        self,
        base_url: str,
        *,
        model: str,
        api_key: str | None,
        timeout: float,
        allow_private: bool,
    ) -> CompletionProbe: ...


def probe_connection(
    settings: Settings,
    endpoints: AgentEndpoints,
    payload: AgentTestRequest,
    *,
    row: AgentsRow | None,
    agent_id: str | None,
) -> ProbeOutcome:
    """Probe ``payload``, completed from the stored ``row`` when there is one; nothing is saved."""
    connection_type = payload.connection_type or (
        row.connection_type if row else "openai_compatible"
    )
    base_url = payload.base_url or (row.base_url if row else "")
    if not base_url:
        raise ValidationFailure(
            "An endpoint is required to test a connection",
            details={"field": "base_url"},
        )
    api_key = payload.api_key
    if payload.no_api_key:
        # Explicit: this endpoint is called without a credential, stored one or not.
        api_key = None
    elif api_key is None and row is not None and row.api_key_ciphertext:
        try:
            api_key = open_secret(settings, row.api_key_ciphertext)
        except CredentialError:
            api_key = None
    fallback_timeout = row.timeout_seconds if row else 30
    timeout = float(payload.timeout_seconds or fallback_timeout)
    fallback_model = row.model if row else ""
    selected_model = (payload.model or fallback_model or "").strip()
    allow_private = settings.agents_allow_private_endpoints
    validated = endpoints.validate_endpoint(base_url, allow_private=allow_private)

    # One pair of events per attempt: an operator reading the log can tell a refused credential
    # from a model the endpoint does not serve, without the request or the key ever appearing.
    _log_probe(
        "agent_probe_started",
        agent_id=agent_id,
        connection_type=connection_type,
        endpoint=validated,
        model=selected_model,
        has_api_key=bool(api_key),
        timeout_seconds=timeout,
    )
    probe = (
        endpoints.probe_openai_compatible
        if connection_type == "openai_compatible"
        else endpoints.probe_a2a
    )
    try:
        found = probe(validated, api_key=api_key, timeout=timeout, allow_private=allow_private)
    except Exception as exc:  # the probe reports, it does not raise
        _log_probe(
            "agent_probe_failed",
            agent_id=agent_id,
            connection_type=connection_type,
            endpoint=validated,
            reason=type(exc).__name__,
        )
        raise
    result: ProbeOutcome = {
        "ok": found["ok"],
        "status": found["status"],
        "message": found["message"],
        "latency_ms": found["latency_ms"],
        "models": found["models"],
        "supports_json_schema": False,
    }

    completion: CompletionProbe | None = None
    if result["ok"] and connection_type == "openai_compatible" and selected_model:
        completion = endpoints.probe_completion(
            validated,
            model=selected_model,
            api_key=api_key,
            timeout=timeout,
            allow_private=allow_private,
        )
        result["completion"] = completion
        if completion["ok"]:
            result["supports_json_schema"] = completion["supports_json_schema"]
            result["message"] = (
                f"{result['message']}; model {selected_model} answered "
                f"in {completion['latency_ms']} ms"
            )
        else:
            # The list answered, the model call did not: say so, and keep the model list so the
            # form can still offer what the endpoint knows.
            result["ok"] = False
            result["status"] = completion["status"]
            result["message"] = (
                f"Endpoint answers, but the model call failed. {completion['message']}"
            )

    _log_probe(
        "agent_probe_finished" if result["ok"] else "agent_probe_failed",
        agent_id=agent_id,
        connection_type=connection_type,
        endpoint=validated,
        model=selected_model,
        status=result["status"],
        latency_ms=result["latency_ms"],
        models=len(result["models"]),
        completion_status=completion["status"] if completion else None,
        reason=None if result["ok"] else result["message"][:200],
    )
    return result


def _log_probe(event: str, **fields: object) -> None:
    started_or_finished = event in {"agent_probe_started", "agent_probe_finished"}
    level = logging.INFO if started_or_finished else logging.WARNING
    logger.log(level, event, extra=fields)
