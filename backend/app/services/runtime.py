"""Agent runtime: call an OpenAI-compatible endpoint and extract a structured position."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx

from ..core.errors import ValidationFailure
from ..core.secrets import CredentialError, open_secret

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


def provider_error(response: httpx.Response) -> str:
    """The status plus the provider's own words, bounded.

    "HTTP 400" alone tells nobody anything: it was the whole message a person saw when a generation
    silently failed. The provider usually says what it disliked ("model not found", "temperature
    unsupported"), so that sentence travels with the status. Only the provider's error text is
    read — never the request, which carries the prompt.
    """
    detail = ""
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
            payload = json.loads(blob)
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


def _agent_key(settings: Any, agent_row: dict[str, Any]) -> str | None:
    if not agent_row.get("api_key_ciphertext"):
        return None
    try:
        return open_secret(settings, agent_row["api_key_ciphertext"])
    except CredentialError as exc:
        raise ValidationFailure("Agent credential cannot be decrypted") from exc


def _transcript(system_prompt: str, messages: list[dict[str, str]]) -> str:
    """One A2A message carries the whole exchange; the protocol has no system role."""
    lines = [f"[instructions]\n{system_prompt}"] if system_prompt else []
    for message in messages:
        role = message.get("role", "user")
        lines.append(f"[{role}]\n{message.get('content', '')}")
    return "\n\n".join(lines)


def _text_parts(value: Any) -> list[str]:
    """Every text part under ``parts``, whatever shape a server answered with."""
    texts: list[str] = []
    if isinstance(value, dict):
        parts = value.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
        for key in ("artifacts", "status", "message"):
            nested = value.get(key)
            if isinstance(nested, dict):
                texts.extend(_text_parts(nested))
            elif isinstance(nested, list):
                for entry in nested:
                    texts.extend(_text_parts(entry))
    return texts


def call_a2a(
    settings: Any,
    agent_row: dict[str, Any],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Send one message over the A2A protocol and return the answer text.

    The card is fetched first because it names the RPC endpoint (``url``); a plain base URL is used
    when the card does not carry one. The answer is collected from message parts, task artifacts or
    the task status, in that order of likelihood.
    """
    api_key = _agent_key(settings, agent_row)
    base_url = str(agent_row["base_url"]).rstrip("/")
    timeout = float(agent_row.get("timeout_seconds") or 60)
    headers = _agent_headers(api_key)
    endpoint = base_url
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            card_url = (
                base_url if base_url.endswith(".json") else f"{base_url}/.well-known/agent.json"
            )
            try:
                card = client.get(card_url, headers={**headers, "Accept": "application/json"})
                if card.status_code < 400:
                    payload = card.json()
                    if isinstance(payload, dict) and isinstance(payload.get("url"), str):
                        endpoint = payload["url"]
            except (httpx.HTTPError, ValueError):
                # A missing card is not fatal: many deployments expose the RPC endpoint directly.
                endpoint = base_url
            payload = {
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
    except Exception as exc:  # noqa: BLE001 - surfaced as an agent failure
        return {"ok": False, "error": f"{type(exc).__name__}", "text": ""}
    if response.status_code >= 400:
        return {"ok": False, "error": provider_error(response), "text": ""}
    try:
        body = response.json()
    except ValueError:
        return {"ok": False, "error": "malformed_response", "text": ""}
    if isinstance(body, dict) and body.get("error"):
        code = str((body.get("error") or {}).get("code") or "a2a_error")
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
    settings: Any,
    agent_row: dict[str, Any],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Call an agent and return the raw answer, whichever transport it speaks.

    Loop planning, RoadMap and QA generation reuse this provider call; discussion verdict
    extraction stays a separate concern layered on top of it.
    """
    if str(agent_row.get("connection_type") or "openai_compatible") == "a2a":
        return call_a2a(settings, agent_row, system_prompt=system_prompt, messages=messages)
    api_key = _agent_key(settings, agent_row)
    headers = _agent_headers(api_key)
    payload = {
        "model": agent_row.get("model") or "default",
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "temperature": (
            temperature
            if temperature is not None
            else (agent_row["temperature"] if agent_row.get("temperature") is not None else 0.3)
        ),
    }
    limit = max_tokens or agent_row.get("max_output_tokens")
    if limit:
        payload["max_tokens"] = limit
    url = f"{str(agent_row['base_url']).rstrip('/')}/chat/completions"
    timeout = float(agent_row.get("timeout_seconds") or 60)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(url, headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001 - surfaced as an agent failure
        return {"ok": False, "error": f"{type(exc).__name__}", "text": ""}
    if response.status_code >= 400:
        return {
            "ok": False,
            "error": provider_error(response),
            "text": "",
        }
    try:
        body = response.json()
        text = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return {"ok": False, "error": "malformed_response", "text": ""}
    return {
        "ok": True,
        "error": None,
        "text": str(text).strip(),
        "model": body.get("model") or payload["model"],
        "usage": body.get("usage") or {},
    }


def call_agent(
    settings: Any,
    agent_row: dict[str, Any],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Discussion-oriented call: the answer carries a structured position."""
    result = call_completion(
        settings, agent_row, system_prompt=system_prompt, messages=messages
    )
    if not result["ok"]:
        return {**result, "verdict": "abstain", "justification": ""}
    verdict, justification = extract_position(result["text"])
    return {**result, "verdict": verdict, "justification": justification}
