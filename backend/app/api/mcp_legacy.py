"""MCP revision 2025-06-18 over Streamable HTTP, as pure functions over plain data.

``/mcp`` is dual-era: it speaks revision 2026-07-28 (``mcp_protocol``) and this older one on the
same address, so that a client of either keeps its connection. Revision 2026-07-28 allows it: "A
server that wishes to support both legacy clients (which expect an ``initialize`` handshake) and
modern clients (which use per-request metadata) MAY implement both behaviors", and "A dual-era
server MAY serve both eras concurrently on the same endpoint or process."

Which revision answers a request is ``selects_legacy``. The specification says how a dual-era
server chooses: "A dual-era server selects its behavior from how the client opens: A request
carrying modern per-request ``_meta`` is served statelessly according to this revision. An
``initialize`` request selects legacy semantics, scoped to the stdio process (stdio) or the session
(HTTP)". Tralala keeps no session, and the specification is silent on how a server without one
knows a request that follows ``initialize``; the simplest rule that needs no state judges each
request by itself, in this order:

1. a body that is not a JSON object goes to 2026-07-28, whose 400 with -32600 both revisions give;
2. ``initialize`` follows 2025-06-18;
3. a request that carries ``io.modelcontextprotocol/protocolVersion`` in ``params._meta`` follows
   2025-06-18 when that names 2025-06-18, and 2026-07-28 otherwise, as the sentence above says of
   a request carrying that ``_meta``; the 2026-07-28 rules refuse a version neither speaks;
4. any other request follows 2026-07-28 when its ``MCP-Protocol-Version`` header names 2026-07-28
   (whose rules then refuse the missing ``_meta``), and 2025-06-18 otherwise: a client of 2025-06-18
   sends no ``_meta`` version and names the version it negotiated in that header, or sends none.

So -32022 answers only a version that neither revision speaks.

The rules of 2025-06-18, as ``dispatch`` checks them; the first rule a request breaks answers it:

1. a body that is not one JSON-RPC 2.0 request or notification: 400 with -32600, as in 2026-07-28;
2. a notification (``notifications/initialized`` among them): 202 and no body;
3. ``initialize``: its result names 2025-06-18 whatever the client asked for, since "If the server
   supports the requested protocol version, it MUST respond with the same version. Otherwise, the
   server MUST respond with another protocol version it supports." The result carries the
   capabilities, ``serverInfo`` and the same instructions ``server/discover`` gives. No session id
   is minted: a server "MAY assign a session ID at initialization time", and this one does not;
4. an ``MCP-Protocol-Version`` header that names a version neither revision speaks: 400 and
   -32022 with ``supported`` and ``requested``, since "If the server receives a request with an
   invalid or unsupported MCP-Protocol-Version, it MUST respond with 400 Bad Request"; 2025-06-18
   names no code, and -32022 is the one 2026-07-28 gives a version it does not speak. A request
   without the header is served as 2025-06-18: the fallback to 2025-03-26 applies only when the
   server "has no other way to identify the version", and every ``initialize`` here negotiates
   2025-06-18. A header that names 2026-07-28 reaches these rules only beside a ``_meta`` that
   names 2025-06-18, and the body's version is the one served;
5. ``ping``: an empty result;
6. ``tools/list``: the tools the key's scopes open, as in 2026-07-28;
7. ``tools/call``: params that are not an object, no string name, arguments that are not an object,
   an unknown tool or a scope the key lacks are -32602 with HTTP 200; otherwise the tool to run;
8. any other method: -32601 with HTTP 200.

The errors after the first rule keep HTTP 200, as this revision's route always answered them,
except -32022, which the specification makes a 400. GET and DELETE answer 405 in both revisions:
2025-06-18 lets a server "return HTTP 405 Method Not Allowed, indicating that the server does not
offer an SSE stream at this endpoint", and answer a DELETE with 405 when it "does not allow clients
to terminate sessions". Results carry no ``resultType`` and no ``_meta``, which this revision does
not have.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ApiError
from ..services.agent_tools import AgentTool, missing_scopes, tool_catalog
from .mcp_protocol import (
    LEGACY_VERSION,
    META_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_HEADER,
    SUPPORTED_VERSIONS,
    Reply,
    RequestId,
    ServerIdentity,
    ToolInvocation,
    envelope,
    failure_content,
    header_values,
    tool_call,
    tool_content,
    tool_failure,
    tool_list,
    tool_result,
    unsupported_version,
)

LEGACY_METHODS = ("initialize", "ping", "tools/list", "tools/call")

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


@dataclass(frozen=True, slots=True)
class LegacyToolCall:
    """A 2025-06-18 ``tools/call`` that passed every check: the handler to run and its
    arguments."""

    message_id: RequestId
    tool: AgentTool
    arguments: dict[str, JsonValue]


def _result(message_id: RequestId, result: Mapping[str, object]) -> Reply:
    return Reply(200, {"jsonrpc": "2.0", "id": message_id, "result": result})


def _error(message_id: RequestId, code: int, message: str) -> Reply:
    error: dict[str, object] = {"code": code, "message": message}
    return Reply(200, {"jsonrpc": "2.0", "id": message_id, "error": error})


def selects_legacy(headers: Iterable[tuple[str, str]], message: JsonValue) -> bool:
    """Whether revision 2025-06-18 answers this message rather than 2026-07-28, by the module's
    rule: ``initialize``; a ``_meta`` version of 2025-06-18; or no ``_meta`` version and no
    2026-07-28 header."""
    if not isinstance(message, dict):
        return False
    if message.get("method") == "initialize":
        return True
    params = message.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    if isinstance(meta, dict) and META_PROTOCOL_VERSION in meta:
        return meta[META_PROTOCOL_VERSION] == LEGACY_VERSION
    named = header_values(headers).get(PROTOCOL_VERSION_HEADER.lower(), [])
    return PROTOCOL_VERSION not in named


def initialize_result(server: ServerIdentity) -> dict[str, object]:
    """What ``initialize`` answers, whatever version the client asked for."""
    return {
        "protocolVersion": LEGACY_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": server.name, "version": server.version},
        "instructions": server.instructions,
    }


def header_version_refusal(
    headers: Iterable[tuple[str, str]], message_id: RequestId
) -> Reply | None:
    """400 and -32022 when the ``MCP-Protocol-Version`` header names a version that neither
    revision speaks; None when it is absent or names a spoken one."""
    for named in header_values(headers).get(PROTOCOL_VERSION_HEADER.lower(), []):
        if named not in SUPPORTED_VERSIONS:
            return unsupported_version(message_id, named)
    return None


def _tool_call(
    message_id: RequestId, params: JsonValue, actor: ActorContext
) -> Reply | LegacyToolCall:
    call = tool_call(params)
    if isinstance(call, str):
        return _error(message_id, INVALID_PARAMS, call)
    name, arguments = call
    tool = tool_catalog().get(name)
    if tool is None:
        return _error(message_id, INVALID_PARAMS, f"Unknown tool: {name}")
    missing = missing_scopes(tool, actor)
    if missing:
        return _error(message_id, INVALID_PARAMS, "Missing required scope: " + ", ".join(missing))
    return LegacyToolCall(message_id, tool, arguments)


def dispatch(
    headers: Iterable[tuple[str, str]],
    message: JsonValue,
    actor: ActorContext,
    server: ServerIdentity,
) -> Reply | LegacyToolCall:
    """One POSTed 2025-06-18 message, checked in the module's order: the answer, or the tool to
    run. ``actor`` is the key the request authenticated with; nothing in the body says who calls.
    """
    read = envelope(message)
    if isinstance(read, Reply):
        return read
    message_id, method, params = read.message_id, read.method, read.params
    if message_id is None:  # notifications/initialized and the like: accepted, never answered
        return Reply(202, None)
    if method == "initialize":
        return _result(message_id, initialize_result(server))
    refusal = header_version_refusal(headers, message_id)
    if refusal is not None:
        return refusal
    if method == "ping":
        return _result(message_id, {})
    if method == "tools/list":
        return _result(message_id, {"tools": tool_list(actor)})
    if method == "tools/call":
        return _tool_call(message_id, params, actor)
    return _error(message_id, METHOD_NOT_FOUND, f"Method not found: {method}")


def call_result(
    step: ToolInvocation | LegacyToolCall, server: ServerIdentity, payload: Mapping[str, object]
) -> Reply:
    """A handler's answer in the revision its call came in."""
    if isinstance(step, ToolInvocation):
        return tool_result(step, server, payload)
    return _result(step.message_id, tool_content(payload))


def call_failure(
    step: ToolInvocation | LegacyToolCall, server: ServerIdentity, error: ApiError
) -> Reply:
    """A handler's refusal, a result with ``isError`` true, in the revision its call came in."""
    if isinstance(step, ToolInvocation):
        return tool_failure(step, server, error)
    return _result(step.message_id, failure_content(error))


__all__ = [
    "LEGACY_METHODS",
    "LegacyToolCall",
    "call_failure",
    "call_result",
    "dispatch",
    "header_version_refusal",
    "initialize_result",
    "selects_legacy",
]
