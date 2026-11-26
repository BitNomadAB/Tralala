"""The texts about ``/mcp`` say what ``app.api.mcp_protocol`` and ``app.api.mcp_legacy`` do.

The route module's docstring, the instructions a model is given, section 5 of ``/llms.txt`` and
the shipped documents describe both revisions the endpoint speaks on its one address, 2026-07-28
and 2025-06-18, and none says that only one is spoken or that an older client is refused. The
requests the documents tell a person to send are chosen and dispatched as the route chooses and
dispatches them, so a document cannot drift from the server. The refusals the documents quote are
the server's own, the sentences about clients are the ones that were checked, and the guide under
Settings builds the command the guide for coding agents gives.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.api import mcp
from app.api.mcp_legacy import LEGACY_METHODS, LegacyToolCall, selects_legacy
from app.api.mcp_legacy import dispatch as dispatch_legacy
from app.api.mcp_protocol import (
    LEGACY_VERSION,
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
DOCUMENTS = (
    "Agent_usage.md",
    "API.md",
    "Architecture.md",
    "Installation.md",
    "Onboarding.md",
    "Release_notes.md",
    "Security_defaults.md",
    "Troubleshooting.md",
)
# What the documents said while the server spoke one revision; none of it is true any more.
ONE_REVISION = re.compile(
    r"2026-07-28 alone|2026-07-28 and no other|speaks only|no older (one|revision)|"
    r"refuses a client of an older revision|older client is refused|cannot connect: it opens"
)
# The client facts that were checked, and claims about clients that were not.
TRIED = (
    "On 2026-11-26 Claude Code (the VS Code extension) and Codex each connected to a Tralala that "
    "spoke revision 2025-06-18 only, and called tools."
)
UNTRIED = "No client has been tried against the 2026-07-28 path."
NO_STREAM = (
    "A client of 2025-06-18 has no way to be asked a question without a stream, and Tralala opens "
    "none; a later tool gives such a client the link to a decision as text."
)
UNCHECKED_CLAIMS = re.compile(
    r"2\.1\.274|2\.1\.232|Cursor|GitHub Copilot|Gemini CLI|MCP_SDK_GENERATION|"
    r"MCP_PROTOCOL_NEGOTIATION"
)

BASH_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)
TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.DOTALL)
HEADER_OPTION = re.compile(r'-H "([^":]+): ([^"]*)"')
BODY_OPTION = re.compile(r"-d '([^']*)'")


def _flat(text: str) -> str:
    """The text with its whitespace collapsed, so a rewrap changes nothing."""
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _document(name: str) -> str:
    return (PUBLIC_DOCS / name).read_text(encoding="utf-8")


def _connect() -> str:
    """Section 2 of the guide for coding agents, as written."""
    return _between(_document("Agent_usage.md"), "\n## 2. Connect\n", "\n## 3. ")


def _mcp_endpoint() -> str:
    """The subsection of API.md that describes ``/mcp``."""
    return _between(_document("API.md"), "\n### The MCP endpoint\n", "\n### ")


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


def _route(pairs: Iterable[tuple[str, str]], message: JsonValue) -> Reply:
    """What the route answers before a handler runs: it chooses the revision and dispatches."""
    pairs = list(pairs)
    if selects_legacy(pairs, message):
        step = dispatch_legacy(pairs, message, WORKER, mcp.SERVER)
        assert not isinstance(step, LegacyToolCall), step
        return step
    reply = dispatch(pairs, message, WORKER, mcp.SERVER)
    assert isinstance(reply, Reply), reply
    return reply


def _decoded(reply: Reply) -> JsonValue:
    """The body exactly as the route sends it, read back as JSON."""
    response = mcp.send(reply)
    value: JsonValue = json.loads(bytes(response.body))
    return value


def _unsupported_message() -> str:
    """The message of -32022, as a client of either revision gets it for a version not spoken."""
    reply = _route(
        [("MCP-Protocol-Version", "2025-11-25")],
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert reply.status == 400
    answer = _decoded(reply)
    assert isinstance(answer, dict)
    error = answer["error"]
    assert isinstance(error, dict)
    assert error["code"] == -32022
    message = error["message"]
    assert isinstance(message, str)
    return message


# --- the texts the server gives ------------------------------------------------------------------


def test_the_route_module_describes_both_revisions() -> None:
    docstring = _flat(mcp.__doc__ or "")
    for part in (PROTOCOL_VERSION, LEGACY_VERSION, *HEADERS, *META_KEYS, *METHODS):
        assert part in docstring, part
    for method in LEGACY_METHODS:
        assert f"``{method}``" in docstring, method
    for part in ("two MCP revisions on the one address", "400 with -32022", "404, -32601", "405"):
        assert part in docstring, part
    assert "No session id is minted" in docstring


def test_the_instructions_name_no_handshake() -> None:
    """``server/discover`` and ``initialize`` hand a model the same instructions; they say how to
    work, not how to connect, so nothing in them names a handshake or a revision."""
    assert not re.search(r"initiali[sz]e|handshake|\bping\b", mcp.INSTRUCTIONS, re.IGNORECASE)
    assert PROTOCOL_VERSION not in mcp.INSTRUCTIONS
    assert LEGACY_VERSION not in mcp.INSTRUCTIONS


def test_llms_txt_tells_an_agent_both_revisions_their_headers_and_their_methods(
    settings: Settings,
) -> None:
    tools = _flat(_between(mcp.render_bootstrap(settings), "\n## 5. Tools\n", "\n### "))
    assert (
        f"in two MCP revisions on the one address, {PROTOCOL_VERSION} and {LEGACY_VERSION}" in tools
    )
    for part in (*HEADERS, *META_KEYS, *METHODS, *LEGACY_METHODS, *CODES):
        assert f"`{part}" in tools, part
    assert "with no session and no stream in either" in tools
    assert f"`MCP-Protocol-Version: {LEGACY_VERSION}` and no `_meta` version" in tools
    assert ONE_REVISION.search(tools) is None


# --- what the documents tell a person ------------------------------------------------------------


@pytest.mark.parametrize("document", ["Agent_usage.md", "Installation.md"])
def test_the_requests_the_documents_show_are_answered(document: str) -> None:
    """Each ``curl`` to ``/mcp`` a person copies from these pages gets 200 and the tool list, in
    the revision the route chooses for it."""
    requests = curl_requests(_document(document))
    assert requests, f"{document} shows no request to /mcp"
    tools: JsonValue = json.loads(json.dumps(tool_list(WORKER)))
    for pairs, message in requests:
        reply = _route(pairs, message)
        answer = _decoded(reply)
        assert reply.status == 200, answer
        assert isinstance(answer, dict)
        result = answer["result"]
        assert isinstance(result, dict)
        assert result["tools"] == tools
        assert ("resultType" in result) is not selects_legacy(pairs, message)


def test_the_guide_asks_in_each_revision() -> None:
    requests = curl_requests(_connect())
    assert sorted(selects_legacy(pairs, message) for pairs, message in requests) == [False, True]


def test_the_guide_says_how_the_revisions_are_told_apart_and_what_was_tried() -> None:
    clients = _flat(_between(_connect(), "### Which clients can connect", "### Connect Claude"))
    assert (
        f"A client connects if it speaks MCP {PROTOCOL_VERSION} or {LEGACY_VERSION}." in clients
    )
    assert f"Tralala answers it with {LEGACY_VERSION}, whatever version the client asked for" in (
        clients
    )
    for sentence in (TRIED, UNTRIED, NO_STREAM):
        assert sentence in clients, sentence
    connect = _flat(_connect())
    assert "claude mcp add --transport http tralala" in connect
    assert '--header "Authorization: Bearer trl_..."' in connect


def test_the_guide_connects_codex_as_its_documentation_says() -> None:
    codex = _between(_connect(), "### Connect Codex\n", "\n### ")
    (block,) = TOML_BLOCK.findall(codex)
    assert block.splitlines() == [
        "[mcp_servers.tralala]",
        'url = "https://tralala.example.com/mcp"',
        'bearer_token_env_var = "TRALALA_TOKEN"',
    ]
    text = _flat(codex)
    assert "`~/.codex/config.toml`" in text
    assert "`codex mcp add tralala --url https://tralala.example.com/mcp`" in text
    assert "Codex sends it in the `Authorization` header" in text
    said = "This is what Codex's own documentation said on 2026-11-26. It names no MCP revision"
    assert said in text
    assert '"returned during initialization"' in text


@pytest.mark.parametrize("document", [*DOCUMENTS, "../README.md"])
def test_no_document_says_one_revision_alone_or_an_unchecked_client_claim(document: str) -> None:
    text = _flat(_document(document))
    assert ONE_REVISION.search(text) is None, ONE_REVISION.search(text)
    assert UNCHECKED_CLAIMS.search(text) is None, UNCHECKED_CLAIMS.search(text)


def test_the_release_notes_state_only_the_checked_client_facts() -> None:
    text = _flat(_document("Release_notes.md"))
    assert TRIED.removesuffix(".") in text
    assert "no client has been tried against the 2026-07-28 path" in text


def test_api_md_lists_both_revisions_their_methods_the_headers_and_every_refusal() -> None:
    endpoint = _flat(_mcp_endpoint())
    for part in (*METHODS, *LEGACY_METHODS, *HEADERS, *META_KEYS, *CODES, "-32600", "-32700"):
        assert f"`{part}" in endpoint, part
    for status in ("`403`", "`405`", "`404`", "`202`"):
        assert status in endpoint, status
    for heading in (f"#### Revision {PROTOCOL_VERSION}", f"#### Revision {LEGACY_VERSION}"):
        assert heading in _mcp_endpoint(), heading
    assert f'"{_unsupported_message()}"' in endpoint


@pytest.mark.parametrize("document", DOCUMENTS)
def test_the_documents_name_both_revisions_mcp_speaks(document: str) -> None:
    text = _document(document)
    assert PROTOCOL_VERSION in text
    assert LEGACY_VERSION in text


def test_troubleshooting_quotes_the_refusal_of_a_version_not_spoken() -> None:
    text = _document("Troubleshooting.md")
    section = _flat(_between(text, "\n## Coding agents and `/mcp`\n", "\n## "))
    assert "answers `400` with `-32022`" in section
    assert f'"{_unsupported_message()}"' in section
    assert "An `initialize` itself is never refused" in section
    assert "(Agent_usage.md#when-it-does-not-connect)" in section


def test_initialize_is_answered_whatever_version_it_asks_for() -> None:
    """What the documents say of ``initialize``: never a refusal, always 2025-06-18."""
    for requested in ("2025-06-18", "2025-11-25", "1900-01-01"):
        message: JsonValue = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {"protocolVersion": requested, "capabilities": {}, "clientInfo": {}},
        }
        reply = _route([], message)
        answer = _decoded(reply)
        assert reply.status == 200
        assert isinstance(answer, dict)
        result = answer["result"]
        assert isinstance(result, dict)
        assert result["protocolVersion"] == LEGACY_VERSION
        assert result["instructions"] == mcp.INSTRUCTIONS


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
    -32602 error with HTTP 200, not a 403, in either revision. The documents quote both."""
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
    legacy_call: JsonValue = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "whoami", "arguments": {}},
    }
    legacy = dispatch_legacy([(HEADERS[0], LEGACY_VERSION)], legacy_call, reader, mcp.SERVER)
    assert isinstance(legacy, Reply) and legacy.status == 200
    assert _quoted(legacy) == _quoted(scoped)
    for document in ("Security_defaults.md", "Troubleshooting.md"):
        text = _flat(_document(document))
        assert _quoted(untrusted) in text, document
        assert _quoted(scoped) in text, document
        for setting in ("TRALALA_PUBLIC_URL", "TRALALA_CORS_ORIGINS"):
            assert setting in text, (document, setting)


def test_the_settings_guide_builds_the_documented_command_for_both_revisions() -> None:
    """The guide under Settings gives the command section 2 gives, with the address and the key
    as its arguments, and names both revisions ``/mcp`` speaks."""
    source = (FRONTEND / "lib" / "agentAccess.ts").read_text(encoding="utf-8")
    assert f'export const MCP_REVISION = "{PROTOCOL_VERSION}";' in source
    assert f'export const MCP_LEGACY_REVISION = "{LEGACY_VERSION}";' in source
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


def test_the_readme_names_both_revisions_mcp_speaks() -> None:
    readme = (PUBLIC_DOCS.parent / "README.md").read_text(encoding="utf-8")
    worker = _flat(_between(readme, "**One worker surface**", "\n\n"))
    assert (
        f"speaks MCP revisions {PROTOCOL_VERSION} and {LEGACY_VERSION} on the one address" in worker
    )
