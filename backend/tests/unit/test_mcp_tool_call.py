"""A ``tools/call`` whose params, name or arguments do not have their JSON types is a JSON-RPC
invalid-params error (-32602), never a server error."""

from __future__ import annotations

import pytest
from pydantic import JsonValue

from app.api.mcp_protocol import tool_call


def test_a_call_names_its_tool_and_arguments() -> None:
    assert tool_call({"name": "read_loop", "arguments": {"loop_id": "l-1"}}) == (
        "read_loop",
        {"loop_id": "l-1"},
    )


@pytest.mark.parametrize("params", [{"name": "whoami"}, {"name": "whoami", "arguments": None}])
def test_missing_arguments_read_as_empty(params: JsonValue) -> None:
    assert tool_call(params) == ("whoami", {})


@pytest.mark.parametrize("params", ["read_loop", ["read_loop"], 5, True])
def test_params_that_are_not_an_object_are_invalid(params: JsonValue) -> None:
    assert tool_call(params) == "params must be an object"


@pytest.mark.parametrize("params", [{}, {"name": None}, {"name": 7}, {"name": ["read_loop"]}])
def test_a_call_without_a_string_name_is_invalid(params: JsonValue) -> None:
    """``CallToolRequestParams.name`` is a required string in revision 2026-07-28."""
    assert tool_call(params) == "params.name must be a string"


@pytest.mark.parametrize("arguments", ["x", [1], 3, [], False])
def test_arguments_that_are_not_an_object_are_invalid(arguments: JsonValue) -> None:
    assert tool_call({"name": "read_loop", "arguments": arguments}) == (
        "arguments must be an object"
    )
