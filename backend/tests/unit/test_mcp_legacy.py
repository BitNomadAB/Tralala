"""``/mcp`` also speaks MCP revision 2025-06-18, on the same address as 2026-07-28.

Which revision answers a request is ``selects_legacy``, and the older revision's rules are pure
functions in ``app.api.mcp_legacy``: these tests hand them a request's header pairs, its parsed
body and an actor, and check what comes back. Nothing builds the application, opens a database or
sends a request.
"""

from __future__ import annotations

import json

import pytest
from pydantic import JsonValue

from app.api import mcp
from app.api.mcp_legacy import (
    LegacyToolCall,
    call_failure,
    call_result,
    dispatch,
    header_version_refusal,
    initialize_result,
    selects_legacy,
)
from app.api.mcp_protocol import ToolInvocation, tool_failure, tool_list, tool_result
from app.api.mcp_protocol import dispatch as dispatch_modern
from app.core.context import SCOPES, ActorContext
from app.core.errors import Forbidden

LEGACY = "2025-06-18"
MODERN = "2026-07-28"
WORKER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="worker", scopes=frozenset(SCOPES)
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="reader", scopes=frozenset({"boards:read"})
)
SPOKEN = [MODERN, LEGACY]
UNSUPPORTED = (
    "Unsupported protocol version: Tralala speaks MCP 2026-07-28, and MCP 2025-06-18 after "
    "initialize"
)


def request(
    method: str, params: JsonValue = None, *, message_id: JsonValue = 1
) -> dict[str, JsonValue]:
    """A request as a client of 2025-06-18 sends it: no ``_meta`` version."""
    body: dict[str, JsonValue] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def initialize(requested: JsonValue = LEGACY) -> dict[str, JsonValue]:
    return request(
        "initialize",
        {
            "protocolVersion": requested,
            "capabilities": {"elicitation": {}},
            "clientInfo": {"name": "legacy-client", "version": "1.0.0"},
        },
        message_id=0,
    )


def headers(version: str | None = LEGACY) -> list[tuple[str, str]]:
    """The header pairs a client of 2025-06-18 sends after ``initialize``, as Starlette hands
    them over; without the version header when ``version`` is None."""
    pairs = [
        ("content-type", "application/json"),
        ("accept", "application/json, text/event-stream"),
    ]
    if version is not None:
        pairs.append(("mcp-protocol-version", version))
    return pairs


def answer(
    message: JsonValue, pairs: list[tuple[str, str]], actor: ActorContext = WORKER
) -> tuple[int, dict[str, JsonValue]]:
    """The HTTP status and the body, read back through JSON so it is proven serialisable."""
    step = dispatch(pairs, message, actor, mcp.SERVER)
    assert not isinstance(step, LegacyToolCall), step
    assert step.body is not None
    body: JsonValue = json.loads(json.dumps(step.body))
    assert isinstance(body, dict)
    return step.status, body


def tool(message: JsonValue, pairs: list[tuple[str, str]]) -> LegacyToolCall:
    step = dispatch(pairs, message, WORKER, mcp.SERVER)
    assert isinstance(step, LegacyToolCall), step
    return step


def modern_meta(version: str) -> dict[str, JsonValue]:
    return {
        "io.modelcontextprotocol/protocolVersion": version,
        "io.modelcontextprotocol/clientCapabilities": {},
    }


# --- which revision answers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "pairs", "legacy"),
    [
        (initialize(), [], True),
        (initialize(), headers(MODERN), True),
        (request("tools/list"), headers(), True),
        (request("tools/list"), headers(None), True),
        (request("tools/list"), [("MCP-PROTOCOL-VERSION", LEGACY)], True),
        (request("tools/list"), headers("2025-11-25"), True),
        (request("tools/list"), headers(MODERN), False),
        (request("tools/list"), [("Mcp-Protocol-Version", MODERN)], False),
        (request("tools/list", {"_meta": modern_meta(MODERN)}), headers(MODERN), False),
        (request("tools/list", {"_meta": modern_meta(MODERN)}), [], False),
        (request("tools/list", {"_meta": modern_meta("2027-01-01")}), headers(), False),
        (request("tools/list", {"_meta": modern_meta(LEGACY)}), headers(MODERN), True),
        (request("tools/list", {"_meta": {"progressToken": 1}}), headers(), True),
        (request("ping", "not an object"), headers(), True),
        ([request("tools/list")], headers(), False),
        ("tools/list", headers(), False),
    ],
)
def test_the_revision_follows_how_the_request_opens(
    message: JsonValue, pairs: list[tuple[str, str]], legacy: bool
) -> None:
    """``initialize`` and a request without a ``_meta`` version and a 2026-07-28 header are the
    older revision's; a ``_meta`` version picks its own revision; a body that is not an object
    goes to 2026-07-28, whose -32600 is the same."""
    assert selects_legacy(pairs, message) is legacy


def test_a_request_of_either_revision_gets_its_own_answer_on_the_one_address() -> None:
    """The same method, once per revision: the older answer has no ``resultType``."""
    older = request("tools/list")
    assert selects_legacy(headers(), older)
    _, legacy_body = answer(older, headers())
    newer: JsonValue = request("tools/list", {"_meta": modern_meta(MODERN)})
    pairs = [("mcp-protocol-version", MODERN), ("mcp-method", "tools/list")]
    assert not selects_legacy(pairs, newer)
    modern_step = dispatch_modern(pairs, newer, WORKER, mcp.SERVER)
    assert not isinstance(modern_step, ToolInvocation)
    assert modern_step.body is not None
    modern_result = modern_step.body["result"]
    assert isinstance(modern_result, dict)
    assert legacy_body["result"] == {"tools": tool_list(WORKER)}
    assert modern_result["tools"] == tool_list(WORKER)
    assert modern_result["resultType"] == "complete"


# --- initialize ----------------------------------------------------------------------------------


@pytest.mark.parametrize("requested", [LEGACY, "2025-11-25", "2025-03-26", "2024-11-05", 2025])
def test_initialize_negotiates_2025_06_18_whatever_was_asked(requested: JsonValue) -> None:
    """The server answers the version it supports when it does not speak the one asked for, and
    never refuses the handshake."""
    status, body = answer(initialize(requested), [])
    assert status == 200
    assert body == {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": LEGACY,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "tralala", "version": "1.0.0"},
            "instructions": mcp.INSTRUCTIONS,
        },
    }


@pytest.mark.parametrize("params", [None, {}, "2025-06-18"])
def test_initialize_without_its_params_still_negotiates(params: JsonValue) -> None:
    status, body = answer(request("initialize", params, message_id="init"), [])
    assert status == 200
    assert body["result"] == initialize_result(mcp.SERVER)
    assert body["id"] == "init"


def test_initialize_ignores_a_version_header_and_mints_no_session() -> None:
    step = dispatch(headers("1900-01-01"), initialize(), WORKER, mcp.SERVER)
    assert not isinstance(step, LegacyToolCall)
    assert step.status == 200
    assert step.headers == {}
    assert "mcp-session-id" not in mcp.send(step).headers


def test_the_older_and_the_newer_client_are_given_the_same_instructions() -> None:
    assert initialize_result(mcp.SERVER)["instructions"] == mcp.INSTRUCTIONS


# --- the version header --------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["2025-11-25", "2025-03-26", "1900-01-01", ""])
def test_a_version_header_neither_revision_speaks_is_400_unsupported(version: str) -> None:
    status, body = answer(request("tools/list"), headers(version))
    assert status == 400
    assert body == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {
            "code": -32022,
            "message": UNSUPPORTED,
            "data": {"supported": SPOKEN, "requested": version},
        },
    }


def test_a_request_without_the_version_header_is_served_as_2025_06_18() -> None:
    assert answer(request("tools/list"), headers(None)) == answer(request("tools/list"), headers())


def test_the_body_version_is_served_beside_a_header_for_2026_07_28() -> None:
    message = request("tools/list", {"_meta": modern_meta(LEGACY)})
    assert header_version_refusal(headers(MODERN), 1) is None
    assert answer(message, headers(MODERN)) == answer(request("tools/list"), headers())


def test_a_repeated_header_is_refused_by_the_first_unspoken_value() -> None:
    pairs = [("mcp-protocol-version", LEGACY), ("MCP-Protocol-Version", "2099-01-01")]
    refusal = header_version_refusal(pairs, 3)
    assert refusal is not None
    assert refusal.status == 400
    assert refusal.body is not None
    assert refusal.body["error"] == {
        "code": -32022,
        "message": UNSUPPORTED,
        "data": {"supported": SPOKEN, "requested": "2099-01-01"},
    }


# --- methods -------------------------------------------------------------------------------------


def test_ping_answers_an_empty_result() -> None:
    assert answer(request("ping", message_id="p"), headers()) == (
        200,
        {"jsonrpc": "2.0", "id": "p", "result": {}},
    )


def test_tools_list_names_the_tools_the_key_holds() -> None:
    status, body = answer(request("tools/list"), headers(), READER)
    assert status == 200
    assert body == {"jsonrpc": "2.0", "id": 1, "result": {"tools": tool_list(READER)}}
    assert [entry["name"] for entry in tool_list(READER)] == ["whoami", "list_boards"]


def test_a_tool_call_names_the_handler_and_its_arguments_without_mcp_name() -> None:
    step = tool(
        request("tools/call", {"name": "read_loop", "arguments": {"loop_id": "l-1"}}), headers()
    )
    assert step.message_id == 1
    assert step.tool.name == "read_loop"
    assert step.arguments == {"loop_id": "l-1"}


@pytest.mark.parametrize(
    ("params", "actor", "message"),
    [
        ("whoami", WORKER, "params must be an object"),
        ({"arguments": {}}, WORKER, "params.name must be a string"),
        ({"name": "whoami", "arguments": [1]}, WORKER, "arguments must be an object"),
        ({"name": "archive_board"}, WORKER, "Unknown tool: archive_board"),
        ({"name": "read_loop"}, READER, "Missing required scope: loops:read"),
    ],
)
def test_a_tool_call_it_cannot_run_is_invalid_params_with_http_200(
    params: JsonValue, actor: ActorContext, message: str
) -> None:
    assert answer(request("tools/call", params), headers(), actor) == (
        200,
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": message}},
    )


@pytest.mark.parametrize("method", ["server/discover", "resources/list", "Tools/List"])
def test_a_method_this_revision_does_not_have_is_method_not_found_with_http_200(
    method: str,
) -> None:
    assert answer(request(method), headers()) == (
        200,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        },
    )


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}},
    ],
)
def test_a_notification_is_accepted_with_202_and_no_body(message: JsonValue) -> None:
    step = dispatch(headers(), message, WORKER, mcp.SERVER)
    assert not isinstance(step, LegacyToolCall)
    assert (step.status, step.body) == (202, None)


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": None, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 1},
    ],
)
def test_a_body_that_is_not_one_request_is_400_invalid_request(message: JsonValue) -> None:
    status, body = answer(message, headers())
    assert status == 400
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == -32600


# --- a tool's answer -----------------------------------------------------------------------------


def test_a_tool_answer_has_text_and_structured_content_and_no_result_type() -> None:
    step = tool(request("tools/call", {"name": "whoami"}), headers())
    reply = call_result(step, mcp.SERVER, {"name": "worker", "notices": []})
    assert reply.status == 200
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": '{"name": "worker", "notices": []}'}],
            "structuredContent": {"name": "worker", "notices": []},
            "isError": False,
        },
    }


def test_a_tool_refusal_is_a_result_with_is_error() -> None:
    step = tool(request("tools/call", {"name": "whoami"}), headers())
    error = Forbidden("approve analysis is a human decision", code="human_action_required")
    text = json.dumps(
        {
            "error": {
                "code": "human_action_required",
                "message": "approve analysis is a human decision",
                "details": None,
                "retryable": False,
            }
        }
    )
    reply = call_failure(step, mcp.SERVER, error)
    assert reply.body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": text}], "isError": True},
    }


def test_a_call_of_the_newer_revision_is_answered_in_its_own_shape() -> None:
    message: JsonValue = request(
        "tools/call", {"name": "whoami", "arguments": {}, "_meta": modern_meta(MODERN)}
    )
    pairs = [
        ("mcp-protocol-version", MODERN),
        ("mcp-method", "tools/call"),
        ("mcp-name", "whoami"),
    ]
    step = dispatch_modern(pairs, message, WORKER, mcp.SERVER)
    assert isinstance(step, ToolInvocation)
    payload = {"name": "worker"}
    assert call_result(step, mcp.SERVER, payload) == tool_result(step, mcp.SERVER, payload)
    error = Forbidden("no", code="human_action_required")
    assert call_failure(step, mcp.SERVER, error) == tool_failure(step, mcp.SERVER, error)


def test_a_2025_06_18_call_of_ask_person_brings_no_input_and_is_never_asked() -> None:
    """A client of 2025-06-18 has no stream to be asked on: its call of ``ask_person`` carries no
    modes, answers or state (``LegacyToolCall`` has none), the route runs the catalogue handler
    through ``run_tool``, and that handler answers with the decision's address as text
    (``test_agent_tools_decisions``). Even ``inputResponses`` and ``requestState`` in its params
    are not read."""
    params: JsonValue = {
        "name": "ask_person",
        "arguments": {"board_id": "b", "loop_id": "l", "decision": "analysis"},
        "inputResponses": {"decision": {"action": "accept"}},
        "requestState": "state",
    }
    step = tool(request("tools/call", params), headers())
    assert step.tool.name == "ask_person"
    assert step.tool.asks is not None
    assert not hasattr(step, "input_context")
    assert step.arguments == {"board_id": "b", "loop_id": "l", "decision": "analysis"}
