"""Agent runtime: call an OpenAI-compatible endpoint and extract a structured position."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..core.errors import ValidationFailure
from ..core.secrets import CredentialError, open_secret

VERDICT_PATTERN = re.compile(r"\b(AGREE|DISAGREE|ABSTAIN)\b", re.IGNORECASE)


def extract_position(text: str) -> tuple[str, str]:
    """Return ``(verdict, justification)`` from the tail of an agent answer."""
    matches = list(VERDICT_PATTERN.finditer(text))
    if not matches:
        return "abstain", ""
    last = matches[-1]
    return last.group(1).lower(), text[: last.start()].strip()[-800:]


def call_completion(
    settings: Any,
    agent_row: dict[str, Any],
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Call an OpenAI-compatible endpoint and return the raw answer.

    Loop planning, RoadMap and QA generation reuse this provider call; discussion verdict
    extraction stays a separate concern layered on top of it.
    """
    api_key = None
    if agent_row.get("api_key_ciphertext"):
        try:
            api_key = open_secret(settings, agent_row["api_key_ciphertext"])
        except CredentialError as exc:
            raise ValidationFailure("Agent credential cannot be decrypted") from exc
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
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
            "error": f"HTTP {response.status_code}",
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
