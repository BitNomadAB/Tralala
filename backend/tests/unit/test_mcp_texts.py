"""The texts about ``/mcp`` say what ``app.api.mcp_protocol`` does.

The route module's docstring, the instructions ``server/discover`` gives a model, section 5 of
``/llms.txt`` and the shipped documents describe revision 2026-07-28 and nothing older. The
requests the documents tell a person to send, and the refusal they show for ``initialize``, are run
through ``dispatch`` as the route runs them, so a document cannot drift from the server. The
refusals the documents quote are the server's own, and the guide under Settings builds the command
the guide for coding agents gives, for the revision the server speaks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.api import mcp
from app.api.mcp_protocol import (
    METHODS,
    PROTOCOL_VERSION,
    Reply,
    dispatch,
    origin_refusal,
    tool_list,
)
from app.core.config import Settings
from app.core.context import SCOPES, ActorContext

PUBLIC_DOCS = Path(__file__).resolve().parents[3] / "public_docs"
FRONTEND = PUBLIC_DOCS.parent / "frontend" / "src"
WORKER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="worker", scopes=frozenset(SCOPES)
)
HEADERS = ("MCP-Protocol-Version", "Mcp-Method", "Mcp-Name")
META_KEYS = (
    "io.modelcontextprotocol/protocolVersion",
    "io.modelcontextprotocol/clientCapabilities",
)
CODES = ("-32602", "-32020", "-32022", "-32601")
CLIENTS = ("Claude Code", "Codex CLI", "Cursor", "VS Code with GitHub Copilot", "Gemini CLI")

BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)
HEADER_OPTION = re.compile(r'-H "([^":]+): ([^"]*)"')
BODY_OPTION = re.compile(r"-d '([^']*)'")


def _flat(text: str) -> str:
    """The text with its whitespace collapsed, so a rewrap changes nothing."""
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _connect() -> str:
    """Section 2 of the guide for coding agents, as written."""
    text = (PUBLIC_DOCS / "Agent_usage.md").read_text(encoding="utf-8")
    return _between(text, "\n## 2. Connect\n", "\n## 3. ")


def _mcp_endpoint() -> str:
    """The subsection of API.md that describes ``/mcp``."""
    text = (PUBLIC_DOCS / "API.md").read_text(encoding="utf-8")
    return _between(text, "\n### The MCP endpoint\n", "\n### ")


def curl_requests(markdown: str) -> list[tuple[list[tuple[str, str]], JsonValue]]:
    """Every ``curl`` POST to ``/mcp`` in the text's Bash blocks: its header pairs and its body."""
    found: list[tuple[list[tuple[str, str]], JsonValue]] = []
    for block in BASH_BLOCK.findall(markdown):
        for command in block.replace("\\\n", " ").splitlines():
            if not command.strip().startswith("curl") or "/mcp" not in command:
                continue
            body = BODY_OPTION.search(command)
            assert body is not None, command
            message: JsonValue = json.loads(body.group(1))
            found.append((HEADER_OPTION.findall(command), message))
    return found


def _legacy_initialize(message_id: JsonValue, requested: JsonValue) -> JsonValue:
    """An ``initialize`` as a client of an older revision opens: no headers and no ``_meta``."""
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "initialize",
        "params": {
            "protocolVersion": requested,
            "capabilities": {},
            "clientInfo": {"name": "older-client", "version": "1.0.0"},
        },
    }


def _decoded(reply: Reply) -> JsonValue:
    """The body exactly as the route sends it, read back as JSON."""
    response = mcp.send(reply)
    value: JsonValue = json.loads(bytes(response.body))
    return value


# --- the texts the server gives ------------------------------------------------------------------


def test_the_route_module_describes_the_revision_and_what_is_gone() -> None:
    docstring = _flat(mcp.__doc__ or "")
    for part in (PROTOCOL_VERSION, *HEADERS, *META_KEYS, *METHODS):
        assert part in docstring, part
    for part in ("no ``initialize`` and no ``ping``", "400 with -32022", "404, -32601", "405"):
        assert part in docstring, part


def test_the_instructions_name_no_handshake() -> None:
    """``server/discover`` hands a model the instructions; they say how to work, not how to
    connect, so nothing in them names the handshake the revision does not have."""
    assert not re.search(r"initiali[sz]e|handshake|\bping\b", mcp.INSTRUCTIONS, re.IGNORECASE)


def test_llms_txt_tells_an_agent_the_revision_its_headers_and_its_methods(
    settings: Settings,
) -> None:
    tools = _flat(_between(mcp.render_bootstrap(settings), "\n## 5. Tools\n", "\n### "))
    assert f"in MCP revision {PROTOCOL_VERSION} and no other" in tools
    for part in (*HEADERS, *META_KEYS, *METHODS, "initialize", "ping", *CODES):
        assert f"`{part}" in tools, part
    assert "There is no handshake, no session and no stream." in tools
    assert f"a message that names {PROTOCOL_VERSION}" in tools


# --- what the documents tell a person ------------------------------------------------------------


@pytest.mark.parametrize("document", ["Agent_usage.md", "Installation.md"])
def test_the_requests_the_documents_show_are_answered(document: str) -> None:
    """Each ``curl`` to ``/mcp`` a person copies from these pages gets 200 and the tool list."""
    requests = curl_requests((PUBLIC_DOCS / document).read_text(encoding="utf-8"))
    assert requests, f"{document} shows no request to /mcp"
    tools: JsonValue = json.loads(json.dumps(tool_list(WORKER)))
    for pairs, message in requests:
        reply = dispatch(pairs, message, WORKER, mcp.SERVER)
        assert isinstance(reply, Reply), reply
        answer = _decoded(reply)
        assert reply.status == 200, answer
        assert isinstance(answer, dict)
        result = answer["result"]
        assert isinstance(result, dict)
        assert result["resultType"] == "complete"
        assert result["tools"] == tools


def _initialize_error(message_id: JsonValue, requested: JsonValue) -> dict[str, JsonValue]:
    """The whole answer an older client's ``initialize`` gets, which must be a 400."""
    reply = dispatch([], _legacy_initialize(message_id, requested), WORKER, mcp.SERVER)
    assert isinstance(reply, Reply)
    assert reply.status == 400
    answer = _decoded(reply)
    assert isinstance(answer, dict)
    return answer


def test_the_refusal_the_guide_shows_is_the_one_initialize_gets() -> None:
    """The guide shows the answer to an older client word for word, the one it may only see as
    a failed connection, so a person can recognise it."""
    (block,) = [block for block in JSON_BLOCK.findall(_connect()) if "-32022" in block]
    shown: JsonValue = json.loads(block)
    assert isinstance(shown, dict)
    error = shown["error"]
    assert isinstance(error, dict)
    data = error["data"]
    assert isinstance(data, dict)
    assert _initialize_error(shown["id"], data["requested"]) == shown


def test_the_guide_names_the_clients_that_can_connect() -> None:
    clients = _flat(_between(_connect(), "### Which clients can connect", "### Connect Claude"))
    assert f"A client connects only if it speaks MCP {PROTOCOL_VERSION}." in clients
    assert "None of them has been tried against Tralala yet" in clients
    for client in CLIENTS:
        assert client in clients, client
    connect = _flat(_connect())
    assert "claude mcp add --transport http tralala" in connect
    assert '--header "Authorization: Bearer trl_..."' in connect


def test_api_md_lists_the_methods_the_headers_and_every_refusal() -> None:
    endpoint = _flat(_mcp_endpoint())
    for part in (*METHODS, *HEADERS, *META_KEYS, *CODES, "-32600", "-32700"):
        assert f"`{part}" in endpoint, part
    for status in ("`403`", "`405`", "`404`", "`202`"):
        assert status in endpoint, status
    error = _initialize_error(1, "2025-06-18")["error"]
    assert isinstance(error, dict)
    assert f'"{error["message"]}"' in endpoint
    api = (PUBLIC_DOCS / "API.md").read_text(encoding="utf-8")
    assert "`initialize`, `tools/list`, `tools/call`, `ping`" not in api


@pytest.mark.parametrize(
    "document",
    [
        "Agent_usage.md",
        "API.md",
        "Architecture.md",
        "Installation.md",
        "Onboarding.md",
        "Release_notes.md",
        "Security_defaults.md",
        "Troubleshooting.md",
    ],
)
def test_the_documents_name_the_revision_mcp_speaks(document: str) -> None:
    assert PROTOCOL_VERSION in (PUBLIC_DOCS / document).read_text(encoding="utf-8")


def test_troubleshooting_quotes_the_refusal_initialize_gets() -> None:
    text = (PUBLIC_DOCS / "Troubleshooting.md").read_text(encoding="utf-8")
    section = _flat(_between(text, "\n## Coding agents and `/mcp`\n", "\n## "))
    error = _initialize_error(1, "2025-06-18")["error"]
    assert isinstance(error, dict)
    assert error["code"] == -32022
    assert "answers `400` with `-32022`" in section
    assert f'"{error["message"]}"' in section
    assert "(Agent_usage.md#when-it-does-not-connect)" in section


def _quoted(reply: Reply | None) -> str:
    """A refusal's message as the documents quote it: each quoted value and each listed scope
    stands as ``…``."""
    assert isinstance(reply, Reply)
    answer = _decoded(reply)
    assert isinstance(answer, dict)
    error = answer["error"]
    assert isinstance(error, dict)
    message = error["message"]
    assert isinstance(message, str)
    return re.sub(r"(?<=scope: )\S+$", "…", re.sub(r"'[^']*'", "'…'", message))


def test_the_refusals_the_documents_quote_are_the_ones_mcp_sends() -> None:
    """An untrusted ``Origin`` is 403 and a request without one passes; a missing scope is a
    -32602 error with HTTP 200, not a 403. The documents quote both messages."""
    untrusted = origin_refusal("https://elsewhere.example", frozenset())
    assert untrusted is not None and untrusted.status == 403
    assert origin_refusal(None, frozenset()) is None
    reader = ActorContext(
        actor_id="agent-2", actor_type="agent", actor_name="reader", scopes=frozenset()
    )
    pairs = [(HEADERS[0], PROTOCOL_VERSION), (HEADERS[1], "tools/call"), (HEADERS[2], "whoami")]
    meta: JsonValue = {META_KEYS[0]: PROTOCOL_VERSION, META_KEYS[1]: {}}
    call: JsonValue = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "whoami", "arguments": {}, "_meta": meta},
    }
    scoped = dispatch(pairs, call, reader, mcp.SERVER)
    assert isinstance(scoped, Reply) and scoped.status == 200
    for document in ("Security_defaults.md", "Troubleshooting.md"):
        text = _flat((PUBLIC_DOCS / document).read_text(encoding="utf-8"))
        assert _quoted(untrusted) in text, document
        assert _quoted(scoped) in text, document
        for setting in ("TRALALA_PUBLIC_URL", "TRALALA_CORS_ORIGINS"):
            assert setting in text, (document, setting)


def test_the_settings_guide_builds_the_documented_command_for_the_revision() -> None:
    """The guide under Settings gives the command section 2 gives, with the address and the key
    as its arguments, and names the revision ``/mcp`` speaks."""
    source = (FRONTEND / "lib" / "agentAccess.ts").read_text(encoding="utf-8")
    assert f'export const MCP_REVISION = "{PROTOCOL_VERSION}";' in source
    (documented,) = [
        line.strip()
        for block in BASH_BLOCK.findall(_connect())
        for line in block.splitlines()
        if line.strip().startswith("claude mcp add ")
    ]
    template = documented.replace("http://127.0.0.1:8000", "${origin}").replace(
        "trl_...", "${token}"
    )
    assert f"`{template}`" in source


def test_the_readme_names_the_revision_mcp_speaks() -> None:
    readme = (PUBLIC_DOCS.parent / "README.md").read_text(encoding="utf-8")
    worker = _flat(_between(readme, "**One worker surface**", "\n\n"))
    assert f"speaks MCP revision {PROTOCOL_VERSION} alone" in worker
