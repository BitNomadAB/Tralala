"""``/mcp`` speaks MCP revision 2026-07-28, beside 2025-06-18 (``test_mcp_legacy``).

Every rule of the revision is a pure function in ``app.api.mcp_protocol``: these tests hand it a
request's header pairs, its parsed body and an actor, and check the HTTP status, the JSON-RPC code
and the body that come back. Nothing builds the application, opens a database or sends a request;
the route only resolves the actor, reads the body, chooses the revision, dispatches and runs the
handler.
"""

from __future__ import annotations

import ast
import base64
import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import JsonValue

from app.api import mcp
from app.api.mcp_protocol import (
    ElicitationModes,
    InputContext,
    Reply,
    ToolInvocation,
    asked_result,
    dispatch,
    elicitation_modes,
    header_text,
    origin_refusal,
    parse_error,
    state_refused,
    tool_failure,
    tool_input,
    tool_list,
    tool_result,
    trusted_origins,
)
from app.core.config import Settings
from app.core.context import SCOPES, ActorContext
from app.core.errors import Forbidden
from app.services.agent_tools import InputRequired, ToolInput

VERSION = "2026-07-28"
WORKER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="worker", scopes=frozenset(SCOPES)
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="reader", scopes=frozenset({"boards:read"})
)
SERVER_META = {"io.modelcontextprotocol/serverInfo": {"name": "tralala", "version": "1.0.0"}}
API_ROOT = Path(__file__).resolve().parents[2] / "app" / "api"


def meta(version: str = VERSION, capabilities: JsonValue = None) -> dict[str, JsonValue]:
    """``params._meta`` as a client of revision 2026-07-28 sends it."""
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientInfo": {"name": "ExampleClient", "version": "1.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {} if capabilities is None else capabilities,
    }


def request(
    method: str,
    params: dict[str, JsonValue] | None = None,
    *,
    message_id: JsonValue = 1,
    version: str = VERSION,
    capabilities: JsonValue = None,
) -> dict[str, JsonValue]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": method,
        "params": {**(params or {}), "_meta": meta(version, capabilities)},
    }


def headers(method: str, name: str | None = None, version: str = VERSION) -> list[tuple[str, str]]:
    """The header pairs a client of revision 2026-07-28 sends, as Starlette hands them over."""
    pairs = [
        ("content-type", "application/json"),
        ("accept", "application/json, text/event-stream"),
        ("mcp-protocol-version", version),
        ("mcp-method", method),
    ]
    if name is not None:
        pairs.append(("mcp-name", name))
    return pairs


def answer(
    message: JsonValue, pairs: list[tuple[str, str]], actor: ActorContext = WORKER
) -> Reply:
    step = dispatch(pairs, message, actor, mcp.SERVER)
    assert isinstance(step, Reply), step
    return step


def invocation(
    message: JsonValue, pairs: list[tuple[str, str]], actor: ActorContext = WORKER
) -> ToolInvocation:
    step = dispatch(pairs, message, actor, mcp.SERVER)
    assert isinstance(step, ToolInvocation), step
    return step


def decoded(reply: Reply) -> dict[str, JsonValue]:
    """The body as the client reads it: through JSON, so it is also proven serialisable."""
    assert reply.body is not None
    value: JsonValue = json.loads(json.dumps(reply.body))
    assert isinstance(value, dict)
    return value


def refusal(reply: Reply) -> tuple[int, JsonValue]:
    """The HTTP status and the JSON-RPC error code of a refused request."""
    error = decoded(reply)["error"]
    assert isinstance(error, dict)
    return reply.status, error["code"]


def call(name: str, arguments: dict[str, JsonValue] | None = None, **extra: JsonValue) -> JsonValue:
    params: dict[str, JsonValue] = {"name": name, "arguments": arguments or {}, **extra}
    return request("tools/call", params)


# --- one revision --------------------------------------------------------------------------------


def test_the_endpoint_speaks_revision_2026_07_28_and_2025_06_18() -> None:
    assert mcp.PROTOCOL_VERSION == "2026-07-28"
    assert mcp.LEGACY_VERSION == "2025-06-18"
    assert mcp.SUPPORTED_VERSIONS == ("2026-07-28", "2025-06-18")


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_only_the_older_revision_answers_initialize_or_ping() -> None:
    """The route has no method branch at all, and revision 2026-07-28 has neither method; only the
    module of 2025-06-18 names them."""
    assert {"initialize", "ping"}.isdisjoint(_string_literals(API_ROOT / "mcp.py"))
    assert {"initialize", "ping"}.isdisjoint(_string_literals(API_ROOT / "mcp_protocol.py"))
    assert {"initialize", "ping"} <= _string_literals(API_ROOT / "mcp_legacy.py")


def test_the_route_resolves_reads_chooses_dispatches_and_runs_the_handler_only() -> None:
    """``mcp_endpoint`` calls nothing but the actor, the body, the pure functions of the two
    revisions and the thread pool; ``test_async_routes`` keeps it the one async route of the
    file."""
    tree = ast.parse((API_ROOT / "mcp.py").read_text(encoding="utf-8"))
    (endpoint,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "mcp_endpoint"
    ]
    called = {
        node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)
        for statement in endpoint.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    }
    assert called == {
        "run_in_threadpool",
        "trusted_origins",
        "origin_refusal",
        "request.headers.get",
        "send",
        "read_limited_json",
        "parse_error",
        "request.headers.items",
        "selects_legacy",
        "dispatch_legacy",
        "dispatch",
        "isinstance",
        "call_failure",
        "call_result",
        # A tool that asks for input (ask_person): what the call brought for it, and its answer.
        "tool_input",
        "tool_failure",
        "state_refused",
        "asked_result",
    }


# --- server/discover -----------------------------------------------------------------------------


def test_server_discover_names_the_version_the_tools_the_server_and_the_instructions() -> None:
    reply = answer(request("server/discover", message_id="discover-1"), headers("server/discover"))
    assert reply.status == 200
    assert reply.headers == {}
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": "discover-1",
        "result": {
            "resultType": "complete",
            "supportedVersions": ["2026-07-28", "2025-06-18"],
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": mcp.INSTRUCTIONS,
            "ttlMs": 3_600_000,
            "cacheScope": "public",
            "_meta": SERVER_META,
        },
    }


def test_server_discover_is_the_same_for_every_key() -> None:
    nobody = ActorContext(actor_id="agent-3", actor_type="agent", actor_name="idle")
    assert answer(request("server/discover"), headers("server/discover"), nobody).body == (
        answer(request("server/discover"), headers("server/discover")).body
    )


# --- tools/list ----------------------------------------------------------------------------------


def test_tools_list_is_complete_and_private_to_the_key() -> None:
    reply = answer(request("tools/list"), headers("tools/list"), READER)
    assert reply.status == 200
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "resultType": "complete",
            "tools": tool_list(READER),
            "ttlMs": 300_000,
            "cacheScope": "private",
            "_meta": SERVER_META,
        },
    }
    assert [tool["name"] for tool in tool_list(READER)] == ["whoami", "list_boards"]
    assert mcp.tool_list is tool_list


# --- tools/call ----------------------------------------------------------------------------------


def test_a_tool_call_names_the_handler_its_arguments_and_its_input_context() -> None:
    step = invocation(call("read_loop", {"loop_id": "l-1"}), headers("tools/call", "read_loop"))
    assert step.message_id == 1
    assert step.tool.name == "read_loop"
    assert step.arguments == {"loop_id": "l-1"}
    assert step.input_context == InputContext(ElicitationModes(), {}, None)


def test_a_tool_answer_is_a_complete_result_with_text_and_structured_content() -> None:
    step = invocation(call("whoami"), headers("tools/call", "whoami"))
    reply = tool_result(step, mcp.SERVER, {"name": "worker", "scopes": ["boards:read"]})
    assert reply.status == 200
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "resultType": "complete",
            "content": [{"type": "text", "text": '{"name": "worker", "scopes": ["boards:read"]}'}],
            "structuredContent": {"name": "worker", "scopes": ["boards:read"]},
            "isError": False,
            "_meta": SERVER_META,
        },
    }


def test_a_tool_refusal_is_a_complete_result_with_is_error() -> None:
    step = invocation(call("whoami"), headers("tools/call", "whoami"))
    error = Forbidden(
        "approve analysis is a human decision",
        code="human_action_required",
        details={"action": "approve analysis", "actor_type": "agent"},
    )
    text = json.dumps(
        {
            "error": {
                "code": "human_action_required",
                "message": "approve analysis is a human decision",
                "details": {"action": "approve analysis", "actor_type": "agent"},
                "retryable": False,
            }
        }
    )
    assert tool_failure(step, mcp.SERVER, error) == Reply(
        200,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "resultType": "complete",
                "content": [{"type": "text", "text": text}],
                "isError": True,
                "_meta": SERVER_META,
            },
        },
    )


def test_an_unknown_tool_or_a_missing_scope_is_invalid_params_as_before() -> None:
    unknown = answer(call("archive_board"), headers("tools/call", "archive_board"))
    assert refusal(unknown) == (200, -32602)
    assert decoded(unknown)["error"] == {"code": -32602, "message": "Unknown tool: archive_board"}
    scoped = answer(call("read_loop"), headers("tools/call", "read_loop"), READER)
    assert decoded(scoped)["error"] == {
        "code": -32602,
        "message": "Missing required scope: loops:read",
    }


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"arguments": {}}, "params.name must be a string"),
        ({"name": "whoami", "arguments": [1]}, "arguments must be an object"),
        ({"name": "whoami", "inputResponses": []}, "params.inputResponses must be an object"),
        (
            {"name": "whoami", "inputResponses": {"ask": "accept"}},
            "params.inputResponses 'ask' must be an object",
        ),
        ({"name": "whoami", "requestState": 5}, "params.requestState must be a string"),
    ],
)
def test_malformed_tool_call_params_are_invalid_params(
    params: dict[str, JsonValue], message: str
) -> None:
    reply = answer(request("tools/call", params), headers("tools/call", "whoami"))
    assert decoded(reply)["error"] == {"code": -32602, "message": message}
    assert reply.status == 200


# --- params._meta --------------------------------------------------------------------------------


def _without(key: str) -> dict[str, JsonValue]:
    return {name: value for name, value in meta().items() if name != key}


@pytest.mark.parametrize(
    ("params", "message"),
    [
        (None, "params must be an object with _meta"),
        ([1], "params must be an object with _meta"),
        ({}, "params._meta must be an object"),
        ({"_meta": "2026-07-28"}, "params._meta must be an object"),
        (
            {"_meta": _without("io.modelcontextprotocol/protocolVersion")},
            "params._meta must carry io.modelcontextprotocol/protocolVersion as a string",
        ),
        (
            {"_meta": {**meta(), "io.modelcontextprotocol/protocolVersion": 20260728}},
            "params._meta must carry io.modelcontextprotocol/protocolVersion as a string",
        ),
        (
            {"_meta": _without("io.modelcontextprotocol/clientCapabilities")},
            "params._meta must carry io.modelcontextprotocol/clientCapabilities as an object",
        ),
        (
            {"_meta": {**meta(), "io.modelcontextprotocol/clientCapabilities": []}},
            "params._meta must carry io.modelcontextprotocol/clientCapabilities as an object",
        ),
    ],
)
@pytest.mark.parametrize("method", ["server/discover", "tools/list", "tools/call", "ping"])
def test_a_request_without_its_meta_is_400_invalid_params(
    method: str, params: JsonValue, message: str
) -> None:
    body: dict[str, JsonValue] = {"jsonrpc": "2.0", "id": 4, "method": method}
    if params is not None:
        body["params"] = params
    reply = answer(body, headers(method, "whoami"))
    assert reply.status == 400
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 4,
        "error": {"code": -32602, "message": message},
    }


def test_client_info_is_optional_and_never_an_identity() -> None:
    """Only the version and the capabilities are required; ``clientInfo`` changes nothing."""
    plain = request("tools/list")
    params = plain["params"]
    assert isinstance(params, dict)
    params["_meta"] = _without("io.modelcontextprotocol/clientInfo")
    assert answer(plain, headers("tools/list")).body == (
        answer(request("tools/list"), headers("tools/list")).body
    )


# --- versions ------------------------------------------------------------------------------------

UNSUPPORTED = (
    "Unsupported protocol version: Tralala speaks MCP 2026-07-28, and MCP 2025-06-18 after "
    "initialize"
)
SPOKEN = ["2026-07-28", "2025-06-18"]


def test_a_version_the_server_does_not_speak_is_400_unsupported() -> None:
    reply = answer(
        request("tools/list", version="2025-11-25"), headers("tools/list", version="2025-11-25")
    )
    assert reply.status == 400
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32022,
            "message": UNSUPPORTED,
            "data": {"supported": SPOKEN, "requested": "2025-11-25"},
        },
    }


def test_the_version_is_checked_before_the_headers_of_a_revision_not_spoken() -> None:
    reply = answer(request("tools/list", version="2027-01-01"), [])
    assert refusal(reply) == (400, -32022)
    assert decoded(reply)["error"] == {
        "code": -32022,
        "message": UNSUPPORTED,
        "data": {"supported": SPOKEN, "requested": "2027-01-01"},
    }


# --- methods and notifications -------------------------------------------------------------------


def test_ping_is_an_unknown_method() -> None:
    reply = answer(request("ping"), headers("ping"))
    assert reply.status == 404
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "Method not found: 'ping'"},
    }


@pytest.mark.parametrize(
    "method",
    [
        "subscriptions/listen",
        "resources/list",
        "resources/read",
        "prompts/list",
        "logging/setLevel",
        "notifications/initialized",
        "Tools/List",
    ],
)
def test_a_method_the_server_does_not_implement_is_404(method: str) -> None:
    assert refusal(answer(request(method), headers(method))) == (404, -32601)


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
        {"jsonrpc": "2.0", "method": "anything", "params": "not even an object"},
    ],
)
def test_a_notification_is_accepted_with_202_and_no_body(message: JsonValue) -> None:
    assert answer(message, []) == Reply(202, None)


# --- the shape of a message ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}],
        "tools/list",
        None,
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
        {"id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": None, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": True, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 1.5, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": {"n": 1}, "method": "tools/list"},
        {"jsonrpc": "2.0", "params": {}},
    ],
)
def test_a_body_that_is_not_one_request_is_400_invalid_request_without_an_id(
    message: JsonValue,
) -> None:
    reply = answer(message, headers("tools/list"))
    assert refusal(reply) == (400, -32600)
    assert "id" not in decoded(reply)


def test_a_response_sent_by_a_client_is_an_invalid_request_with_its_id() -> None:
    reply = answer({"jsonrpc": "2.0", "id": 7, "result": {}}, headers("tools/list"))
    assert refusal(reply) == (400, -32600)
    assert decoded(reply)["id"] == 7


def test_a_string_id_is_answered_with_the_same_id() -> None:
    reply = answer(request("tools/list", message_id="list-1"), headers("tools/list"))
    assert decoded(reply)["id"] == "list-1"


def test_a_body_that_is_not_json_is_400_parse_error() -> None:
    error: dict[str, object] = {"code": -32700, "message": "Parse error: the body is not JSON"}
    assert parse_error() == Reply(400, {"jsonrpc": "2.0", "error": error})


# --- headers -------------------------------------------------------------------------------------

BASE = [("content-type", "application/json")]


@pytest.mark.parametrize(
    ("pairs", "message"),
    [
        (
            [*BASE, ("mcp-method", "tools/list")],
            "Header mismatch: the MCP-Protocol-Version header is missing",
        ),
        (
            [*BASE, ("mcp-protocol-version", "2025-06-18"), ("mcp-method", "tools/list")],
            "Header mismatch: MCP-Protocol-Version header value '2025-06-18' does not match body "
            "value '2026-07-28'",
        ),
        (
            [*BASE, ("mcp-protocol-version", VERSION)],
            "Header mismatch: the Mcp-Method header is missing",
        ),
        (
            [*BASE, ("mcp-protocol-version", VERSION), ("mcp-method", "tools/call")],
            "Header mismatch: Mcp-Method header value 'tools/call' does not match body value "
            "'tools/list'",
        ),
        (
            [*BASE, ("mcp-protocol-version", VERSION), ("mcp-method", "Tools/List")],
            "Header mismatch: Mcp-Method header value 'Tools/List' does not match body value "
            "'tools/list'",
        ),
        (
            [
                *BASE,
                ("mcp-protocol-version", VERSION),
                ("mcp-method", "tools/list"),
                ("mcp-method", "tools/list"),
            ],
            "Header mismatch: the Mcp-Method header appears more than once",
        ),
        (
            [*BASE, ("mcp-protocol-version", VERSION), ("mcp-method", "tööls/list")],
            "Header mismatch: the Mcp-Method header has invalid characters",
        ),
        (
            [*BASE, ("mcp-protocol-version", VERSION + "\n"), ("mcp-method", "tools/list")],
            "Header mismatch: the MCP-Protocol-Version header has invalid characters",
        ),
        (
            [
                *BASE,
                ("mcp-protocol-version", VERSION),
                ("mcp-method", "=?base64?dG9vbHMvbGlzdA==?="),
            ],
            "Header mismatch: Mcp-Method header value '=?base64?dG9vbHMvbGlzdA==?=' does not "
            "match body value 'tools/list'",
        ),
    ],
)
def test_a_missing_or_unlike_header_is_400_header_mismatch(
    pairs: list[tuple[str, str]], message: str
) -> None:
    reply = answer(request("tools/list"), pairs)
    assert reply.status == 400
    assert reply.body == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32020, "message": message}}


def test_header_names_are_compared_without_regard_to_case() -> None:
    pairs = [
        ("MCP-PROTOCOL-VERSION", VERSION),
        ("mCp-MeThOd", "tools/call"),
        ("MCP-NAME", "whoami"),
    ]
    assert invocation(call("whoami"), pairs).tool.name == "whoami"


def _base64(text: str) -> str:
    return "=?base64?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


@pytest.mark.parametrize(
    ("name_header", "message"),
    [
        (None, "Header mismatch: the Mcp-Name header is missing"),
        (
            "read_loop",
            "Header mismatch: Mcp-Name header value 'read_loop' does not match body value "
            "'whoami'",
        ),
        (
            _base64("read_loop"),
            "Header mismatch: Mcp-Name header value 'read_loop' does not match body value "
            "'whoami'",
        ),
        (
            "=?base64?not base64!?=",
            "Header mismatch: the Mcp-Name header has invalid characters or an invalid Base64 form",
        ),
        (
            "=?base64?" + base64.b64encode(b"\xff\xfe").decode("ascii") + "?=",
            "Header mismatch: the Mcp-Name header has invalid characters or an invalid Base64 form",
        ),
        (
            "=?BASE64?" + base64.b64encode(b"whoami").decode("ascii") + "?=",
            "Header mismatch: Mcp-Name header value '=?BASE64?d2hvYW1p?=' does not match body "
            "value 'whoami'",
        ),
        (
            "whoämi",
            "Header mismatch: the Mcp-Name header has invalid characters or an invalid Base64 form",
        ),
    ],
)
def test_a_tool_call_needs_mcp_name_equal_to_its_name(
    name_header: str | None, message: str
) -> None:
    reply = answer(call("whoami"), headers("tools/call", name_header))
    assert reply.status == 400
    assert reply.body == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32020, "message": message}}


def test_mcp_name_in_its_base64_form_is_decoded_before_it_is_compared() -> None:
    step = invocation(call("whoami"), headers("tools/call", _base64("whoami")))
    assert step.tool.name == "whoami"
    # A name outside the safe characters passes the header check and is then an unknown tool.
    unknown = answer(call("wéird ☃"), headers("tools/call", _base64("wéird ☃")))
    assert decoded(unknown)["error"] == {"code": -32602, "message": "Unknown tool: wéird ☃"}


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("us-west1", "us-west1"),
        ("=?base64?SGVsbG8sIOS4lueVjA==?=", "Hello, 世界"),
        ("=?base64?IHBhZGRlZCA=?=", " padded "),
        ("=?base64?bGluZTEKbGluZTI=?=", "line1\nline2"),
        ("=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=", "=?base64?literal?="),
        ("=?base64??=", ""),
        ("=?base64?=", "=?base64?="),
        ("=?base64?SGVsbG8?=", None),
        ("plain\x7f", None),
    ],
)
def test_header_text_decodes_the_base64_form_of_the_specification(
    value: str, text: str | None
) -> None:
    """The encoding examples of the transport page, and two malformed values."""
    assert header_text(value, encoded=True) == text


def test_only_mcp_name_may_use_the_base64_form() -> None:
    assert header_text("=?base64?SGVsbG8sIOS4lueVjA==?=", encoded=False) == (
        "=?base64?SGVsbG8sIOS4lueVjA==?="
    )


def test_session_and_event_ids_are_ignored_and_never_minted() -> None:
    pairs = [
        *headers("tools/list"),
        ("mcp-session-id", "1868a90c-7f3e-4d8a-9b2e-0c1d2e3f4a5b"),
        ("last-event-id", "42"),
    ]
    reply = answer(request("tools/list"), pairs)
    assert reply == answer(request("tools/list"), headers("tools/list"))
    response = mcp.send(reply)
    assert "mcp-session-id" not in response.headers


# --- one JSON answer per POST, and 405 for GET and DELETE ----------------------------------------


def test_every_answer_is_one_json_body_or_none() -> None:
    reply = answer(request("tools/list"), headers("tools/list"))
    response = mcp.send(reply)
    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert json.loads(bytes(response.body)) == decoded(reply)
    accepted = mcp.send(Reply(202, None))
    assert accepted.status_code == 202
    assert accepted.body == b""
    assert "content-type" not in accepted.headers


def test_get_and_delete_are_405_with_allow_post() -> None:
    routes = {
        frozenset(route.methods or ()): route.endpoint
        for route in mcp.router.routes
        if isinstance(route, APIRoute) and route.path == "/mcp"
    }
    assert routes == {
        frozenset({"POST"}): mcp.mcp_endpoint,
        frozenset({"GET", "DELETE"}): mcp.mcp_not_allowed,
    }
    response = mcp.mcp_not_allowed()
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert response.media_type == "application/json"
    assert json.loads(bytes(response.body)) == {
        "jsonrpc": "2.0",
        "error": {
            "code": -32600,
            "message": "Method not allowed: POST each JSON-RPC request to this endpoint; Tralala "
            "opens no stream to GET and keeps no session to DELETE",
        },
    }


# --- Origin --------------------------------------------------------------------------------------

TRUSTED = trusted_origins(
    ["http://localhost:5173", "http://127.0.0.1:5173/"], "https://Tralala.Example.com/base"
)


def test_the_trusted_origins_are_the_cors_origins_and_the_public_url() -> None:
    assert frozenset(
        {"http://localhost:5173", "http://127.0.0.1:5173", "https://tralala.example.com"}
    ) == TRUSTED
    assert trusted_origins(["not an origin", ""], None) == frozenset()


def test_the_settings_name_the_origins_the_route_trusts(settings: Settings) -> None:
    """The route reads both from the installation's settings; a cors_origins entry passes."""
    trusted = trusted_origins(settings.allowed_origins, settings.public_url)
    assert all(origin_refusal(origin, trusted) is None for origin in settings.allowed_origins)


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://tralala.example.com",
        "https://tralala.example.com:443",
        "HTTPS://TRALALA.EXAMPLE.COM",
    ],
)
def test_a_request_without_an_origin_or_from_a_trusted_one_passes(origin: str | None) -> None:
    assert origin_refusal(origin, TRUSTED) is None


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "",
        "http://tralala.example.com",
        "https://tralala.example.com:8443",
        "https://tralala.example.com/base",
        "https://user@tralala.example.com",
        "http://localhost:5174",
    ],
)
def test_an_origin_that_is_present_and_not_trusted_is_403_without_an_id(origin: str) -> None:
    error: dict[str, object] = {
        "code": -32600,
        "message": f"Forbidden: the Origin '{origin}' is not allowed",
    }
    assert origin_refusal(origin, TRUSTED) == Reply(403, {"jsonrpc": "2.0", "error": error})


# --- elicitation and the multi round-trip fields -------------------------------------------------


@pytest.mark.parametrize(
    ("capabilities", "modes"),
    [
        ({}, ElicitationModes()),
        ({"elicitation": {}}, ElicitationModes(form=True)),
        ({"elicitation": {"form": {}}}, ElicitationModes(form=True)),
        ({"elicitation": {"url": {}}}, ElicitationModes(url=True)),
        ({"elicitation": {"form": {}, "url": {}}}, ElicitationModes(form=True, url=True)),
        ({"elicitation": True}, ElicitationModes()),
        ({"elicitation": {"form": True}}, ElicitationModes()),
        ({"elicitation": {"other": {}}}, ElicitationModes()),
    ],
)
def test_the_elicitation_modes_a_client_declares(
    capabilities: dict[str, JsonValue], modes: ElicitationModes
) -> None:
    assert elicitation_modes(capabilities) == modes


def test_a_tool_call_carries_its_modes_answers_and_state_as_one_value() -> None:
    params: dict[str, JsonValue] = {
        "name": "whoami",
        "arguments": {},
        "inputResponses": {"decision": {"action": "accept"}},
        "requestState": "opaque-state",
    }
    message = request("tools/call", params, capabilities={"elicitation": {"url": {}}})
    step = invocation(message, headers("tools/call", "whoami"))
    assert step.input_context == InputContext(
        ElicitationModes(url=True), {"decision": {"action": "accept"}}, "opaque-state"
    )
    # whoami asks for nothing: the route runs its handler as before, and never hands it this.
    assert step.tool.name == "whoami"
    assert step.tool.asks is None
    assert step.arguments == {}


# --- ask_person: input_required -----------------------------------------------------------------


def _ask_person(**extra: JsonValue) -> ToolInvocation:
    arguments: dict[str, JsonValue] = {"board_id": "b", "loop_id": "l", "decision": "analysis"}
    params: dict[str, JsonValue] = {"name": "ask_person", "arguments": arguments, **extra}
    message = request("tools/call", params, capabilities={"elicitation": {"url": {}}})
    return invocation(message, headers("tools/call", "ask_person"))


MESSAGE = "Open Tralala to approve the analysis of L-1 or ask for changes."
ADDRESS = "https://tralala.example.com/boards/b/loops/l?tab=plan&doc=analysis"
QUESTION = InputRequired(
    {
        "decision": {
            "method": "elicitation/create",
            "params": {"mode": "url", "message": MESSAGE, "url": ADDRESS},
        }
    },
    "sealed-state",
)


def test_only_ask_person_is_handed_what_the_call_brought_for_it() -> None:
    step = _ask_person(inputResponses={"decision": {"action": "accept"}}, requestState="s")
    assert step.tool.asks is not None
    assert tool_input(step.input_context) == ToolInput(
        form=False, url=True, responses={"decision": {"action": "accept"}}, request_state="s"
    )


def test_a_question_is_an_input_required_result_with_its_requests_and_state() -> None:
    reply = asked_result(_ask_person(), mcp.SERVER, QUESTION)
    assert reply.status == 200
    assert decoded(reply) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "resultType": "input_required",
            "inputRequests": {
                "decision": {
                    "method": "elicitation/create",
                    "params": {
                        "mode": "url",
                        "message": MESSAGE,
                        "url": ADDRESS,
                    },
                }
            },
            "requestState": "sealed-state",
            "_meta": SERVER_META,
        },
    }


def test_a_complete_answer_of_ask_person_is_a_complete_result() -> None:
    reply = asked_result(_ask_person(), mcp.SERVER, {"status": "waiting_for_person"})
    assert reply == tool_result(_ask_person(), mcp.SERVER, {"status": "waiting_for_person"})


def test_a_refused_state_is_invalid_params_and_says_nothing_about_the_decision() -> None:
    reply = state_refused(7, "ask_person", "expired")
    assert reply.status == 200
    assert decoded(reply) == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32602,
            "message": (
                "Invalid params: the requestState cannot be used (expired). Call ask_person again "
                "without requestState and inputResponses."
            ),
            "data": {"reason": "expired"},
        },
    }


def test_only_tools_call_can_answer_input_required() -> None:
    """``server/discover`` and ``tools/list`` are answered complete by ``dispatch`` itself, and
    the only reply builder that writes ``input_required`` takes a tool call."""
    for method in ("server/discover", "tools/list"):
        result = decoded(answer(request(method), headers(method)))["result"]
        assert isinstance(result, dict)
        assert result["resultType"] == "complete"
    source = (API_ROOT / "mcp_protocol.py").read_text(encoding="utf-8")
    assert source.count('"resultType": "input_required"') == 1
