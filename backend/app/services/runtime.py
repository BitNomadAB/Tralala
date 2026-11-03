"""Agent runtime: call an OpenAI-compatible endpoint and extract a structured position."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import NotRequired, TypedDict, TypeIs

import httpx
from pydantic import JsonValue

from ..core.config import Settings
from ..core.errors import ValidationFailure
from ..core.secrets import CredentialError, open_secret
from . import connections

# Transports that can actually execute a request. Everything that picks an agent for a run asks
# this set instead of naming one transport, so a new transport is added in a single place.
EXECUTABLE_CONNECTION_TYPES = ("a2a", "openai_compatible")

VERDICTS = {"agree", "disagree", "abstain"}
# A verdict is only read from something unambiguous: a JSON object, a `Verdict:` line or a line that
# holds nothing but the word. Matching the bare word anywhere turned "I do not AGREE with this" into
# agreement, which made consensus meaningless.
VERDICT_JSON = re.compile(r"\{[^{}]*\}", re.DOTALL)
VERDICT_LINE = re.compile(
    r"^[ \t>*_#-]*(?:final[ \t]+)?(?:verdict|position)[ \t]*[:=][ \t]*\**[ \t]*"
    r"(AGREE|DISAGREE|ABSTAIN)\b",
    re.IGNORECASE | re.MULTILINE,
)
VERDICT_LONE_LINE = re.compile(
    r"^[ \t>*_#-]*(AGREE|DISAGREE|ABSTAIN)[.!*_ \t]*$", re.IGNORECASE | re.MULTILINE
)


class ResponseSchema(TypedDict):
    """The JSON schema an answer must follow, named as ``response_format`` names it.

    ``name`` is what OpenAI-compatible providers require beside the schema (letters, digits, ``_``
    and ``-``). The schema is sent without ``strict``: strict mode would refuse every schema whose
    optional fields are not all listed as required, and the answer is validated afterwards anyway.
    """

    name: str
    schema: dict[str, JsonValue]


class Completion(TypedDict):
    """What one agent call returned: the answer's text, or the error that stopped it.

    ``model`` and ``usage`` come with an answer only: the model the provider names (else the one
    asked for) and the provider's token counts, as it reported them.
    """

    ok: bool
    error: str | None
    text: str
    model: NotRequired[object]
    usage: NotRequired[JsonValue]


class AgentAnswer(Completion):
    """A discussion answer: the completion and the position read from its text."""

    verdict: str
    justification: str


def _app_settings(settings: object) -> Settings:
    """The application settings, which the agent-call protocols pass on as ``object``."""
    if isinstance(settings, Settings):
        return settings
    raise TypeError(f"an agent call needs the application Settings, not {type(settings).__name__}")


def timeout_error(timeout: float) -> str:
    """A call that ran out of time is the agent's setting, not a provider fault; say which."""
    return f"No answer within {timeout:g} s (the agent's timeout setting)"


def _timeout(agent_row: Mapping[str, object]) -> float:
    """``timeout_seconds`` as ``float()`` reads it; nothing (or zero) is the 60-second default."""
    value = agent_row.get("timeout_seconds") or 60
    if isinstance(value, (int, float, str)):
        return float(value)
    raise TypeError(f"timeout_seconds is not a number: {type(value).__name__}")


def _is_object(value: object) -> TypeIs[dict[str, JsonValue]]:
    """A parsed JSON value that is an object: its keys are strings and its values JSON."""
    return isinstance(value, dict)


def _member(value: JsonValue, key: str | int) -> JsonValue:
    """``value[key]`` of parsed JSON; a ``KeyError``, ``IndexError`` or ``TypeError`` if absent."""
    if isinstance(value, dict):
        if isinstance(key, str):
            return value[key]
        raise KeyError(key)
    if isinstance(value, list) and isinstance(key, int):
        return value[key]
    raise TypeError(f"{type(value).__name__} has no member {key!r}")


def completion_content(body: JsonValue) -> JsonValue:
    """``body["choices"][0]["message"]["content"]``: the answer of a chat completion.

    A body of another shape raises the ``KeyError``, ``IndexError`` or ``TypeError`` that reading
    it by subscript raised, so a caller treats a malformed answer exactly as before.
    """
    return _member(_member(_member(_member(body, "choices"), 0), "message"), "content")


def provider_error(response: httpx.Response) -> str:
    """The status plus the provider's own words, bounded.

    "HTTP 400" alone tells nobody anything: it was the whole message a person saw when a generation
    silently failed. The provider usually says what it disliked ("model not found", "temperature
    unsupported"), so that sentence travels with the status. Only the provider's error text is
    read — never the request, which carries the prompt.
    """
    detail = ""
    body: JsonValue
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        elif isinstance(error, str):
            detail = error
        if not detail:
            detail = str(body.get("message") or body.get("detail") or "")
    if not detail:
        detail = " ".join((response.text or "").split())
    detail = detail.strip()[:200]
    return f"HTTP {response.status_code}" + (f": {detail}" if detail else "")


def refuses_response_format(response: httpx.Response) -> bool:
    """A 400 whose error names ``response_format``: the provider does not take the JSON schema.

    The connection test records whether a provider takes one, but a provider can change under a
    saved agent (another model, an upgrade), so a call that sends the schema checks the refusal
    and asks once more without it.
    """
    return response.status_code == 400 and "response_format" in (response.text or "")


def extract_position(text: str) -> tuple[str, str]:
    """Return ``(verdict, justification)`` from an agent answer, defaulting to ``abstain``."""
    structured = _structured_verdict(text)
    if structured is not None:
        return structured
    matches = list(VERDICT_LINE.finditer(text)) or list(VERDICT_LONE_LINE.finditer(text))
    if not matches:
        return "abstain", ""
    last = matches[-1]
    return last.group(1).lower(), text[: last.start()].strip()[-800:]


def _structured_verdict(text: str) -> tuple[str, str] | None:
    for blob in reversed(VERDICT_JSON.findall(text)):
        try:
            payload: JsonValue = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        raw = payload.get("verdict", payload.get("position"))
        if not isinstance(raw, str) or raw.strip().lower() not in VERDICTS:
            continue
        reasoning = payload.get("reasoning") or payload.get("justification") or ""
        return raw.strip().lower(), str(reasoning).strip()[:800] or text[:800].strip()
    return None


def _agent_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _agent_key(settings: object, agent_row: Mapping[str, object]) -> str | None:
    ciphertext = agent_row.get("api_key_ciphertext")
    if not ciphertext:
        return None
    try:
        return open_secret(_app_settings(settings), str(ciphertext))
    except CredentialError as exc:
        raise ValidationFailure("Agent credential cannot be decrypted") from exc


def _transcript(system_prompt: str, messages: list[dict[str, str]]) -> str:
    """One A2A message carries the whole exchange; the protocol has no system role."""
    lines = [f"[instructions]\n{system_prompt}"] if system_prompt else []
    for message in messages:
        role = message.get("role", "user")
        lines.append(f"[{role}]\n{message.get('content', '')}")
    return "\n\n".join(lines)


def _text_parts(value: object) -> list[str]:
    """Every text part under ``parts``, whatever shape a server answered with."""
    texts: list[str] = []
    if _is_object(value):
        parts = value.get("parts")
        if isinstance(parts, list):
            texts.extend(
                text
                for part in parts
                if isinstance(part, dict) and isinstance(text := part.get("text"), str)
            )
        for key in ("artifacts", "status", "message"):
            nested = value.get(key)
            if isinstance(nested, dict):
                texts.extend(_text_parts(nested))
            elif isinstance(nested, list):
                for entry in nested:
                    texts.extend(_text_parts(entry))
    return texts


def call_a2a(
    settings: object,
    agent_row: Mapping[str, object],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> Completion:
    """Send one message over the A2A protocol and return the answer text.

    The card is fetched first because it names the RPC endpoint (``url``); a plain base URL is used
    when the card does not carry one. The answer is collected from message parts, task artifacts or
    the task status, in that order of likelihood. The card's ``url`` is the agent's own text, so it
    goes through the same pinned client and the endpoint rule holds for it when it is connected to.
    """
    api_key = _agent_key(settings, agent_row)
    base_url = str(agent_row["base_url"]).rstrip("/")
    timeout = _timeout(agent_row)
    headers = _agent_headers(api_key)
    endpoint = base_url
    try:
        with connections.endpoint_client(
            timeout=timeout, allow_private=_app_settings(settings).agents_allow_private_endpoints
        ) as client:
            card_url = (
                base_url if base_url.endswith(".json") else f"{base_url}/.well-known/agent.json"
            )
            try:
                card = client.get(card_url, headers={**headers, "Accept": "application/json"})
                if card.status_code < 400:
                    document: JsonValue = card.json()
                    if isinstance(document, dict) and isinstance(url := document.get("url"), str):
                        endpoint = url
            except (httpx.HTTPError, ValueError):
                # A missing card is not fatal: many deployments expose the RPC endpoint directly.
                endpoint = base_url
            payload: dict[str, JsonValue] = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "messageId": str(uuid.uuid4()),
                        "parts": [{"kind": "text", "text": _transcript(system_prompt, messages)}],
                    },
                    "configuration": {"blocking": True},
                },
            }
            response = client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException:
        return {"ok": False, "error": timeout_error(timeout), "text": ""}
    except Exception as exc:  # noqa: BLE001 - surfaced as an agent failure
        return {"ok": False, "error": f"{type(exc).__name__}", "text": ""}
    if response.status_code >= 400:
        return {"ok": False, "error": provider_error(response), "text": ""}
    body: JsonValue
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "error": "malformed_response", "text": ""}
    if isinstance(body, dict) and (error := body.get("error")):
        if not isinstance(error, dict):
            # Reading the code off an error that is not an object always raised; it still does.
            raise AttributeError(f"'{type(error).__name__}' object has no attribute 'get'")
        code = str(error.get("code") or "a2a_error")
        return {"ok": False, "error": f"a2a:{code}", "text": ""}
    result = body.get("result") if isinstance(body, dict) else None
    text = "\n".join(part.strip() for part in _text_parts(result) if part.strip())
    if not text:
        return {"ok": False, "error": "a2a_empty_response", "text": ""}
    return {
        "ok": True,
        "error": None,
        "text": text,
        "model": str(agent_row.get("model") or "a2a"),
        "usage": {},
    }


def call_completion(
    settings: object,
    agent_row: Mapping[str, object],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_schema: ResponseSchema | None = None,
) -> Completion:
    """Call an agent and return the raw answer, whichever transport it speaks.

    Loop planning, RoadMap and QA generation reuse this provider call; discussion verdict
    extraction stays a separate concern layered on top of it.

    ``response_schema`` is sent as ``response_format`` only to an OpenAI-compatible agent whose
    connection test found that its provider takes a JSON schema (``supports_json_schema``); the
    provider then keeps the answer to the schema instead of the repair loop catching it afterwards.
    A provider that refuses it after all (a 400 that names ``response_format``) is asked once more
    without it, and that answer is returned as if nothing had happened. An A2A agent has no such
    field and never gets it.
    """
    if str(agent_row.get("connection_type") or "openai_compatible") == "a2a":
        return call_a2a(settings, agent_row, system_prompt=system_prompt, messages=messages)
    api_key = _agent_key(settings, agent_row)
    headers = _agent_headers(api_key)
    payload: dict[str, object] = {
        "model": agent_row.get("model") or "default",
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    }
    # Sent only when the caller or the agent chose one: some reasoning models refuse the
    # parameter, and the provider's default is what nobody choosing means.
    chosen = temperature if temperature is not None else agent_row.get("temperature")
    if chosen is not None:
        payload["temperature"] = chosen
    limit = max_tokens or agent_row.get("max_output_tokens")
    if limit:
        payload["max_tokens"] = limit
    if response_schema is not None and agent_row.get("supports_json_schema"):
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": response_schema["name"], "schema": response_schema["schema"]},
        }
    url = f"{str(agent_row['base_url']).rstrip('/')}/chat/completions"
    timeout = _timeout(agent_row)
    try:
        with connections.endpoint_client(
            timeout=timeout, allow_private=_app_settings(settings).agents_allow_private_endpoints
        ) as client:
            response = client.post(url, headers=headers, json=payload)
            if "response_format" in payload and refuses_response_format(response):
                del payload["response_format"]
                response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        return {"ok": False, "error": timeout_error(timeout), "text": ""}
    except Exception as exc:  # noqa: BLE001 - surfaced as an agent failure
        return {"ok": False, "error": f"{type(exc).__name__}", "text": ""}
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": provider_error(response),
            "text": "",
        }
    try:
        answer: JsonValue = response.json()
        text = completion_content(answer)
    except (ValueError, KeyError, IndexError, TypeError):
        return {"ok": False, "error": "malformed_response", "text": ""}
    # Only an object has "choices", so the answer is one here.
    reply = answer if _is_object(answer) else {}
    return {
        "ok": True,
        "error": None,
        "text": str(text).strip(),
        "model": reply.get("model") or payload["model"],
        "usage": reply.get("usage") or {},
    }


def call_agent(
    settings: object,
    agent_row: Mapping[str, object],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AgentAnswer:
    """Discussion-oriented call: the answer carries a structured position."""
    result = call_completion(
        settings, agent_row, system_prompt=system_prompt, messages=messages
    )
    if not result["ok"]:
        return {**result, "verdict": "abstain", "justification": ""}
    verdict, justification = extract_position(result["text"])
    return {**result, "verdict": verdict, "justification": justification}
