"""A2A execution: an A2A agent is called over the protocol, not sent to /chat/completions.

The test runs a real loopback HTTP server that speaks just enough of A2A: an agent card at
`/.well-known/agent.json` and a JSON-RPC `message/send` endpoint. That is the difference between
"the card can be fetched" and "a run gets an answer".
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.core.config import Settings
from app.services import runtime


class _A2AHandler(BaseHTTPRequestHandler):
    server_version = "a2a-stub/1.0"

    def log_message(self, *args: Any) -> None:  # noqa: D102 - keep the test output clean
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        port = self.server.server_address[1]
        if self.path == "/.well-known/agent.json":
            self._send(200, {"name": "Stub agent", "url": f"http://127.0.0.1:{port}/a2a"})
        else:
            self._send(404, {"error": "missing"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("content-length") or 0)
        message = json.loads(self.rfile.read(length) or b"{}")
        self.server.last_request = message  # type: ignore[attr-defined]
        text = message["params"]["message"]["parts"][0]["text"]
        if "trigger-rpc-error" in text:
            self._send(
                200, {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32000}}
            )
            return
        if "trigger-empty-answer" in text:
            self._send(
                200, {"jsonrpc": "2.0", "id": message.get("id"), "result": {"kind": "task"}}
            )
            return
        self._send(
            200,
            {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "kind": "task",
                    "status": {"state": "completed"},
                    "artifacts": [
                        {"parts": [{"kind": "text", "text": f"AGREE\nEcho: {text[-40:]}"}]}
                    ],
                },
            },
        )


@pytest.fixture()
def a2a_server() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _A2AHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _agent_row(port: int, connection_type: str = "a2a") -> dict[str, Any]:
    return {
        "id": "agent-a2a",
        "name": "Stub agent",
        "connection_type": connection_type,
        "base_url": f"http://127.0.0.1:{port}",
        "model": None,
        "temperature": None,
        "max_output_tokens": None,
        "timeout_seconds": 10,
        "api_key_ciphertext": None,
    }


def _settings() -> Settings:
    return Settings(data_dir="unused-in-this-test", secret_key="x" * 40)


def test_an_a2a_agent_is_called_over_message_send(a2a_server: ThreadingHTTPServer) -> None:
    port = a2a_server.server_address[1]
    result = runtime.call_completion(
        _settings(),
        _agent_row(port),
        system_prompt="You are the architect.",
        messages=[{"role": "user", "content": "Is the plan sound?"}],
    )
    assert result["ok"] is True, result
    assert result["text"].startswith("AGREE")

    request = a2a_server.last_request  # type: ignore[attr-defined]
    assert request["method"] == "message/send"
    sent = request["params"]["message"]["parts"][0]["text"]
    assert "You are the architect." in sent
    assert "Is the plan sound?" in sent
    assert request["params"]["configuration"] == {"blocking": True}


def test_a_json_rpc_error_is_reported(a2a_server: ThreadingHTTPServer) -> None:
    port = a2a_server.server_address[1]
    result = runtime.call_a2a(
        _settings(),
        _agent_row(port),
        system_prompt="",
        messages=[{"role": "user", "content": "trigger-rpc-error"}],
    )
    assert result["ok"] is False
    assert result["error"] == "a2a:-32000"


def test_an_answer_without_parts_is_a_failure(a2a_server: ThreadingHTTPServer) -> None:
    port = a2a_server.server_address[1]
    result = runtime.call_a2a(
        _settings(),
        _agent_row(port),
        system_prompt="",
        messages=[{"role": "user", "content": "trigger-empty-answer"}],
    )
    assert result == {"ok": False, "error": "a2a_empty_response", "text": ""}


def test_an_unreachable_a2a_agent_fails_cleanly() -> None:
    result = runtime.call_a2a(
        _settings(),
        _agent_row(9),
        system_prompt="prompt",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["ok"] is False
    assert result["text"] == ""
    assert result["error"]


def test_an_openai_agent_still_uses_chat_completions() -> None:
    row = _agent_row(9, connection_type="openai_compatible")
    row["base_url"] = "http://127.0.0.1:9/v1"
    result = runtime.call_completion(
        _settings(), row, system_prompt="prompt", messages=[{"role": "user", "content": "hi"}]
    )
    # Unreachable, but the error shape proves the OpenAI path ran, not the A2A one.
    assert result == {"ok": False, "error": "ConnectError", "text": ""}
