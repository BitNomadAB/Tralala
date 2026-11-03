"""A ``tools/call`` whose params or arguments are not JSON objects is a JSON-RPC invalid-params
error (-32602), never a server error."""

from __future__ import annotations

import pytest
from pydantic import JsonValue

from app.api.mcp import tool_call


def test_a_call_names_its_tool_and_arguments() -> None:
    assert tool_call({"name": "read_loop", "arguments": {"loop_id": "l-1"}}) == (
        "read_loop",
        {"loop_id": "l-1"},
    )


def test_missing_name_and_arguments_read_as_empty() -> None:
    assert tool_call({}) == ("", {})


@pytest.mark.parametrize("params", ["read_loop", ["read_loop"], 5, True])
def test_params_that_are_not_an_object_are_invalid(params: JsonValue) -> None:
    assert tool_call(params) == "params must be an object"


@pytest.mark.parametrize("arguments", ["x", [1], 3])
def test_arguments_that_are_not_an_object_are_invalid(arguments: JsonValue) -> None:
    assert tool_call({"name": "read_loop", "arguments": arguments}) == (
        "arguments must be an object"
    )
