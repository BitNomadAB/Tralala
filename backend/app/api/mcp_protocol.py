"""MCP revision 2026-07-28 over Streamable HTTP, as pure functions over plain data.

The route in ``mcp.py`` resolves the actor, reads the body and hands this module the request's
header pairs, the parsed body and the actor. What comes back is either the whole answer (a
``Reply``) or the tool to run (a ``ToolInvocation``), whose outcome ``tool_result`` and
``tool_failure`` turn into the answer. Nothing here touches the request, the event loop or a
database, so a unit test calls every rule directly.

The server is dual-era: it also speaks revision 2025-06-18, whose rules live in ``mcp_legacy``,
and ``mcp_legacy.selects_legacy`` says which of the two answers a request. These rules answer a
request that names another version than 2025-06-18 in ``params._meta``, or that names none there
and 2026-07-28 in its ``MCP-Protocol-Version`` header. This revision has no ``initialize``
handshake, no ``ping``, no session and no stream. Every request states its version and its
client's capabilities in ``params._meta`` and mirrors the version and the method (and a tool
call's name) into headers. The route authenticates the key first (401 as REST answers it) and
refuses an untrusted ``Origin`` (403, ``origin_refusal``) before it reads the body; a body that is
not JSON is 400 with -32700 (``parse_error``). ``dispatch`` then checks the rest in this order, and
the first rule a request breaks answers it:

1. a body that is not one JSON-RPC 2.0 request or notification: 400 with -32600;
2. a notification (no ``id``): 202 and no body, since this revision defines none to act on;
3. ``params._meta`` without the protocol version (a string) and the client's capabilities (an
   object): 400 and -32602;
4. a version in ``_meta`` other than 2026-07-28: 400 and -32022 with ``supported`` (both
   revisions) and ``requested``. The route hands a request whose ``_meta`` names 2025-06-18 to
   ``mcp_legacy``, so only a version that neither revision speaks gets this answer from it;
5. ``MCP-Protocol-Version`` or ``Mcp-Method`` missing, repeated, with invalid characters or unlike
   the body: 400 and -32020;
6. a method this revision does not have, ``ping`` among them: 404 and -32601;
7. on ``tools/call``, ``Mcp-Name`` likewise against ``params.name``, its Base64 form decoded first:
   400 and -32020.

Every result carries ``resultType`` and the server's identity in ``_meta``. What a tool call's own
params get wrong (no name, arguments that are not an object, an unknown tool, a scope the key
lacks) stays a -32602 error with HTTP 200, and a handler's refusal is a tool result with
``isError`` true. Header names are compared without regard to case; header values exactly.

A multi round-trip request (the revision's MRTR pattern) is a ``tools/call`` of a tool that asks
for input, and only ``ask_person`` does. Such a tool alone is handed the call's ``InputContext``
(the client's elicitation modes, ``inputResponses`` and ``requestState``) as a ``ToolInput``
(``tool_input``), and its question becomes a result with ``resultType`` ``input_required``,
``inputRequests`` and ``requestState`` (``asked_result``). No other method answers
``input_required``: ``server/discover`` and ``tools/list`` are answered here, complete. A state
that the tool's service refuses is -32602 with HTTP 200 and the reason alone (``state_refused``),
never anything about what the state was about.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ApiError
from ..services.agent_tools import (
    AgentTool,
    InputRequired,
    ToolInput,
    ToolResult,
    missing_scopes,
    tool_catalog,
)

PROTOCOL_VERSION = "2026-07-28"
# The older revision, spoken after ``initialize``; its rules live in ``mcp_legacy``.
LEGACY_VERSION = "2025-06-18"
SUPPORTED_VERSIONS: tuple[str, ...] = (PROTOCOL_VERSION, LEGACY_VERSION)

# JSON-RPC's codes, and the ones MCP reserves for itself (-32020 to -32099).
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
METHOD_HEADER = "Mcp-Method"
NAME_HEADER = "Mcp-Name"
# A header value that is not plain ASCII travels as =?base64?<UTF-8 as Base64>?=; the markers are
# case-sensitive.
BASE64_PREFIX = "=?base64?"
BASE64_SUFFIX = "?="

METHODS = ("server/discover", "tools/list", "tools/call")

# The caching hints server/discover and tools/list carry. The discovery result is the same for
# every key; the tool list depends on the key's scopes, so no cache may share it across keys.
DISCOVER_TTL_MS = 3_600_000
TOOLS_LIST_TTL_MS = 300_000

DEFAULT_PORTS = {"http": 80, "https": 443}
# The longest stretch of a header or body value an error message repeats.
SHOWN_CHARACTERS = 80

type RequestId = str | int


@dataclass(frozen=True, slots=True)
class Reply:
    """One HTTP answer: its status, its JSON body (None for an empty one) and extra headers."""

    status: int
    body: Mapping[str, object] | None
    headers: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    """Who answers: the name and version in every result's ``_meta``, and the instructions that
    ``server/discover`` gives a model."""

    name: str
    version: str
    instructions: str


@dataclass(frozen=True, slots=True)
class ElicitationModes:
    """The elicitation modes a request's client declared; a server asks in no other."""

    form: bool = False
    url: bool = False


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """The per-request fields of ``params._meta``: the version and the client's capabilities."""

    protocol_version: str
    client_capabilities: Mapping[str, JsonValue]

    @property
    def elicitation(self) -> ElicitationModes:
        return elicitation_modes(self.client_capabilities)


@dataclass(frozen=True, slots=True)
class InputContext:
    """What a tool call brings for a multi round-trip request: the modes its client can be asked
    in, and a retry's answers (``inputResponses``) and opaque state (``requestState``).

    The state is attacker-controlled input: whoever reads it verifies it first. Only a tool that
    asks for input (``AgentTool.asks``, ``ask_person``) is handed it, as ``tool_input`` makes it.
    """

    elicitation: ElicitationModes
    input_responses: Mapping[str, Mapping[str, JsonValue]]
    request_state: str | None


@dataclass(frozen=True, slots=True)
class Envelope:
    """A message that is one JSON-RPC 2.0 request or notification: its id (None for a
    notification), its method and its params as they came."""

    message_id: RequestId | None
    method: str
    params: JsonValue


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """A ``tools/call`` that passed every check: the handler to run and what it is given."""

    message_id: RequestId
    tool: AgentTool
    arguments: dict[str, JsonValue]
    input_context: InputContext


def _shown(value: str) -> str:
    """A value quoted for a message, cut so that a long one cannot fill it."""
    cut = value if len(value) <= SHOWN_CHARACTERS else value[:SHOWN_CHARACTERS] + "..."
    return f"'{cut}'"


def _error_body(
    message_id: RequestId | None, code: int, message: str, data: Mapping[str, object] | None = None
) -> dict[str, object]:
    """A JSON-RPC error; without an id when the request's could not be read."""
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    body: dict[str, object] = {"jsonrpc": "2.0"}
    if message_id is not None:
        body["id"] = message_id
    body["error"] = error
    return body


def _error(
    status: int,
    message_id: RequestId | None,
    code: int,
    message: str,
    data: Mapping[str, object] | None = None,
) -> Reply:
    return Reply(status, _error_body(message_id, code, message, data))


def _complete(
    message_id: RequestId, server: ServerIdentity, result: Mapping[str, object]
) -> Reply:
    """A final result: ``resultType`` complete and the server's identity in ``_meta``."""
    return Reply(
        200,
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "resultType": "complete",
                **result,
                "_meta": {META_SERVER_INFO: {"name": server.name, "version": server.version}},
            },
        },
    )


def parse_error() -> Reply:
    """The answer to a body that is not JSON."""
    return _error(400, None, PARSE_ERROR, "Parse error: the body is not JSON")


def method_not_allowed() -> Reply:
    """The answer to GET and DELETE in both revisions: Tralala opens no stream and keeps no
    session, so there is nothing to GET and nothing to DELETE."""
    return Reply(
        405,
        _error_body(
            None,
            INVALID_REQUEST,
            "Method not allowed: POST each JSON-RPC request to this endpoint; Tralala opens no "
            "stream to GET and keeps no session to DELETE",
        ),
        {"Allow": "POST"},
    )


def unsupported_version(message_id: RequestId, requested: str) -> Reply:
    """-32022 for a version this server does not speak, with the ones it does; the message says
    how each is spoken, since an older client may show its person nothing else."""
    return _error(
        400,
        message_id,
        UNSUPPORTED_PROTOCOL_VERSION,
        f"Unsupported protocol version: Tralala speaks MCP {PROTOCOL_VERSION}, and MCP "
        f"{LEGACY_VERSION} after initialize",
        {"supported": list(SUPPORTED_VERSIONS), "requested": requested},
    )


# --- Origin --------------------------------------------------------------------------------------


def _origin_key(value: str, *, exact: bool) -> str | None:
    """An origin as a browser sends it: ``scheme://host[:port]`` in lower case, without a default
    port. ``exact`` refuses anything more (a path, a query, a user), as an ``Origin`` header never
    carries it; a configured address gives its origin. None when there is no scheme and host."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname
    if not scheme or not host:
        return None
    if exact and (parts.path or parts.query or parts.fragment or "@" in parts.netloc):
        return None
    shown_host = f"[{host}]" if ":" in host else host
    if port is None or DEFAULT_PORTS.get(scheme) == port:
        return f"{scheme}://{shown_host}"
    return f"{scheme}://{shown_host}:{port}"


def trusted_origins(allowed_origins: Iterable[str], public_url: str | None) -> frozenset[str]:
    """The origins a browser may call ``/mcp`` from: ``Settings.allowed_origins`` and the origin
    of ``public_url``."""
    candidates = [*allowed_origins, *([public_url] if public_url else [])]
    return frozenset(
        key for value in candidates if (key := _origin_key(value, exact=False)) is not None
    )


def origin_refusal(origin: str | None, trusted: frozenset[str]) -> Reply | None:
    """403 for an ``Origin`` header that is present and not trusted, against DNS rebinding; a
    request without one (a coding agent's, as a rule) passes."""
    if origin is None or _origin_key(origin, exact=True) in trusted:
        return None
    return _error(
        403, None, INVALID_REQUEST, f"Forbidden: the Origin {_shown(origin)} is not allowed"
    )


# --- headers -------------------------------------------------------------------------------------


def header_values(headers: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Every header's values under its lower-case name, since header names ignore case."""
    found: dict[str, list[str]] = {}
    for name, value in headers:
        found.setdefault(name.lower(), []).append(value)
    return found


def _header_safe(value: str) -> bool:
    """Visible ASCII, space and tab: what RFC 9110 allows in a field value."""
    return all(char == "\t" or " " <= char <= "~" for char in value)


def header_text(value: str, *, encoded: bool) -> str | None:
    """A header value as the body carries it, or None when it is malformed. With ``encoded`` (the
    ``Mcp-Name`` header) the form ``=?base64?...?=`` is decoded from Base64 to UTF-8 text first."""
    if (
        encoded
        and len(value) >= len(BASE64_PREFIX) + len(BASE64_SUFFIX)
        and value.startswith(BASE64_PREFIX)
        and value.endswith(BASE64_SUFFIX)
    ):
        encoded_text = value[len(BASE64_PREFIX) : -len(BASE64_SUFFIX)]
        try:
            return base64.b64decode(encoded_text, validate=True).decode("utf-8")
        except ValueError:  # not Base64 (binascii.Error), or not UTF-8
            return None
    return value if _header_safe(value) else None


def header_problem(
    found: Mapping[str, list[str]], header: str, expected: str, *, encoded: bool = False
) -> str | None:
    """Why ``header`` does not carry ``expected``, the body's value; None when it does."""
    values = found.get(header.lower(), [])
    if not values:
        return f"Header mismatch: the {header} header is missing"
    if len(values) > 1:
        return f"Header mismatch: the {header} header appears more than once"
    text = header_text(values[0], encoded=encoded)
    if text is None:
        form = " or an invalid Base64 form" if encoded else ""
        return f"Header mismatch: the {header} header has invalid characters{form}"
    if text != expected:
        return (
            f"Header mismatch: {header} header value {_shown(text)} does not match body value "
            f"{_shown(expected)}"
        )
    return None


# --- the request ---------------------------------------------------------------------------------


def _request_id(value: JsonValue) -> RequestId | None:
    """A request's id as MCP allows it: a string or an integer, never null."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    return value


def elicitation_modes(capabilities: Mapping[str, JsonValue]) -> ElicitationModes:
    """The modes in ``clientCapabilities.elicitation``: ``form`` and ``url`` each as an object,
    and an empty object, as the revision says, for form alone. Anything else declares none."""
    declared = capabilities.get("elicitation")
    if not isinstance(declared, dict):
        return ElicitationModes()
    if not declared:
        return ElicitationModes(form=True)
    return ElicitationModes(
        form=isinstance(declared.get("form"), dict), url=isinstance(declared.get("url"), dict)
    )


def request_meta(params: Mapping[str, JsonValue]) -> RequestMeta | str:
    """The fields every request carries in ``params._meta``, or why the request is malformed."""
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return "params._meta must be an object"
    version = meta.get(META_PROTOCOL_VERSION)
    if not isinstance(version, str):
        return f"params._meta must carry {META_PROTOCOL_VERSION} as a string"
    capabilities = meta.get(META_CLIENT_CAPABILITIES)
    if not isinstance(capabilities, dict):
        return f"params._meta must carry {META_CLIENT_CAPABILITIES} as an object"
    return RequestMeta(version, capabilities)


def tool_call(params: JsonValue) -> tuple[str, dict[str, JsonValue]] | str:
    """A ``tools/call``'s tool name and arguments, or why they are invalid params (-32602)."""
    if not isinstance(params, dict):
        return "params must be an object"
    name = params.get("name")
    if not isinstance(name, str):
        return "params.name must be a string"
    arguments = params.get("arguments")
    if arguments is None:
        return name, {}
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    return name, arguments


def input_context(params: Mapping[str, JsonValue], meta: RequestMeta) -> InputContext | str:
    """A tool call's elicitation modes, ``inputResponses`` and ``requestState`` as one typed
    value, or why they are invalid params (-32602)."""
    responses = params.get("inputResponses")
    if responses is None:
        responses = {}
    if not isinstance(responses, dict):
        return "params.inputResponses must be an object"
    answers: dict[str, Mapping[str, JsonValue]] = {}
    for key, answer in responses.items():
        if not isinstance(answer, dict):
            return f"params.inputResponses {_shown(key)} must be an object"
        answers[key] = answer
    state = params.get("requestState")
    if state is None or isinstance(state, str):
        return InputContext(meta.elicitation, answers, state)
    return "params.requestState must be a string"


def tool_list(actor: ActorContext) -> list[dict[str, object]]:
    """The ``tools/list`` payload: each catalogue entry the actor holds the scopes for, in order."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in tool_catalog().values()
        if not missing_scopes(tool, actor)
    ]


def discover_result(server: ServerIdentity) -> dict[str, object]:
    """What ``server/discover`` answers, the same for every key."""
    return {
        "supportedVersions": list(SUPPORTED_VERSIONS),
        "capabilities": {"tools": {"listChanged": False}},
        "instructions": server.instructions,
        "ttlMs": DISCOVER_TTL_MS,
        "cacheScope": "public",
    }


def _tool_call(
    found: Mapping[str, list[str]],
    message_id: RequestId,
    params: dict[str, JsonValue],
    meta: RequestMeta,
    actor: ActorContext,
) -> Reply | ToolInvocation:
    call = tool_call(params)
    if isinstance(call, str):
        return _error(200, message_id, INVALID_PARAMS, call)
    name, arguments = call
    problem = header_problem(found, NAME_HEADER, name, encoded=True)
    if problem is not None:
        return _error(400, message_id, HEADER_MISMATCH, problem)
    context = input_context(params, meta)
    if isinstance(context, str):
        return _error(200, message_id, INVALID_PARAMS, context)
    tool = tool_catalog().get(name)
    if tool is None:
        return _error(200, message_id, INVALID_PARAMS, f"Unknown tool: {name}")
    missing = missing_scopes(tool, actor)
    if missing:
        return _error(
            200, message_id, INVALID_PARAMS, "Missing required scope: " + ", ".join(missing)
        )
    return ToolInvocation(message_id, tool, arguments, context)


def envelope(message: JsonValue) -> Envelope | Reply:
    """The message as one JSON-RPC 2.0 request or notification, or the 400 with -32600 that a
    body which is neither gets. Both revisions read a message so."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(400, None, INVALID_REQUEST, "Invalid Request: not a JSON-RPC 2.0 message")
    has_id = "id" in message
    message_id = _request_id(message.get("id")) if has_id else None
    method = message.get("method")
    if not isinstance(method, str) or (has_id and message_id is None):
        return _error(
            400,
            message_id,
            INVALID_REQUEST,
            "Invalid Request: a request needs a method and an id that is a string or an integer",
        )
    return Envelope(message_id, method, message.get("params"))


def dispatch(
    headers: Iterable[tuple[str, str]],
    message: JsonValue,
    actor: ActorContext,
    server: ServerIdentity,
) -> Reply | ToolInvocation:
    """One POSTed message, checked in the module's order: the answer, or the tool to run.

    ``headers`` are the request's header pairs as they arrived, ``message`` its parsed body and
    ``actor`` the key it authenticated with; nothing in the body or its ``_meta`` says who calls.
    """
    read = envelope(message)
    if isinstance(read, Reply):
        return read
    message_id, method, params = read.message_id, read.method, read.params
    if message_id is None:  # a notification: nothing defined to act on, and no answer is sent
        return Reply(202, None)
    if not isinstance(params, dict):
        return _error(400, message_id, INVALID_PARAMS, "params must be an object with _meta")
    meta = request_meta(params)
    if isinstance(meta, str):
        return _error(400, message_id, INVALID_PARAMS, meta)
    if meta.protocol_version != PROTOCOL_VERSION:
        return unsupported_version(message_id, meta.protocol_version)
    found = header_values(headers)
    problem = header_problem(found, PROTOCOL_VERSION_HEADER, meta.protocol_version)
    if problem is None:
        problem = header_problem(found, METHOD_HEADER, method)
    if problem is not None:
        return _error(400, message_id, HEADER_MISMATCH, problem)
    if method not in METHODS:
        return _error(404, message_id, METHOD_NOT_FOUND, f"Method not found: {_shown(method)}")
    if method == "server/discover":
        return _complete(message_id, server, discover_result(server))
    if method == "tools/list":
        return _complete(
            message_id,
            server,
            {"tools": tool_list(actor), "ttlMs": TOOLS_LIST_TTL_MS, "cacheScope": "private"},
        )
    return _tool_call(found, message_id, params, meta, actor)


def tool_input(context: InputContext) -> ToolInput:
    """What a call brings for a tool that asks for input, as the services type it."""
    return ToolInput(
        form=context.elicitation.form,
        url=context.elicitation.url,
        responses=context.input_responses,
        request_state=context.request_state,
    )


def input_required(
    invocation: ToolInvocation, server: ServerIdentity, required: InputRequired
) -> Reply:
    """A tool's question as a ``tools/call`` result: ``resultType`` ``input_required``, the
    requests and the state the client repeats the call with, and the server in ``_meta``."""
    return Reply(
        200,
        {
            "jsonrpc": "2.0",
            "id": invocation.message_id,
            "result": {
                "resultType": "input_required",
                "inputRequests": {
                    key: dict(value) for key, value in required.input_requests.items()
                },
                "requestState": required.request_state,
                "_meta": {META_SERVER_INFO: {"name": server.name, "version": server.version}},
            },
        },
    )


def asked_result(
    invocation: ToolInvocation, server: ServerIdentity, answer: ToolResult | InputRequired
) -> Reply:
    """The answer of a tool that asks for input: its question, or its complete result."""
    if isinstance(answer, InputRequired):
        return input_required(invocation, server, answer)
    return tool_result(invocation, server, answer)


def state_refused(message_id: RequestId, tool: str, reason: str) -> Reply:
    """-32602 for a ``requestState`` the tool's service refused: the reason and how to go on,
    nothing about what the state was about."""
    return _error(
        200,
        message_id,
        INVALID_PARAMS,
        f"Invalid params: the requestState cannot be used ({reason}). Call {tool} again without "
        "requestState and inputResponses.",
        {"reason": reason},
    )


def tool_result(
    invocation: ToolInvocation, server: ServerIdentity, payload: Mapping[str, object]
) -> Reply:
    """A handler's answer as a complete ``tools/call`` result: text and structured content."""
    return _complete(invocation.message_id, server, tool_content(payload))


def tool_failure(invocation: ToolInvocation, server: ServerIdentity, error: ApiError) -> Reply:
    """A handler's refusal as a complete ``tools/call`` result with ``isError`` true."""
    return _complete(invocation.message_id, server, failure_content(error))


def tool_content(payload: Mapping[str, object]) -> dict[str, object]:
    """A handler's answer as the ``tools/call`` result of either revision: text and structured
    content."""
    encoded = json.dumps(payload, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": encoded}],
        "structuredContent": payload,
        "isError": False,
    }


def failure_content(error: ApiError) -> dict[str, object]:
    """A handler's refusal as the ``tools/call`` result of either revision, with ``isError``
    true, so the model reads the code, the message and the details and can correct itself."""
    encoded = json.dumps(
        {
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "retryable": error.retryable,
            }
        },
        ensure_ascii=False,
    )
    return {"content": [{"type": "text", "text": encoded}], "isError": True}


__all__ = [
    "LEGACY_VERSION",
    "METHODS",
    "PROTOCOL_VERSION",
    "SUPPORTED_VERSIONS",
    "ElicitationModes",
    "Envelope",
    "InputContext",
    "Reply",
    "RequestMeta",
    "ServerIdentity",
    "ToolInvocation",
    "asked_result",
    "discover_result",
    "dispatch",
    "elicitation_modes",
    "envelope",
    "failure_content",
    "header_problem",
    "header_text",
    "header_values",
    "input_context",
    "input_required",
    "method_not_allowed",
    "origin_refusal",
    "parse_error",
    "request_meta",
    "state_refused",
    "tool_call",
    "tool_content",
    "tool_failure",
    "tool_input",
    "tool_list",
    "tool_result",
    "trusted_origins",
    "unsupported_version",
]
