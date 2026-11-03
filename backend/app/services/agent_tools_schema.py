"""The JSON schemas of the worker catalogue's arguments, as ``tools/list`` serves them.

``agent_tools`` builds each entry's ``inputSchema`` with these helpers; they hold no rule of their
own, only the shape MCP and ``/llms.txt`` read.
"""

from __future__ import annotations

from typing import NotRequired, Required, TypedDict

from pydantic import BaseModel


class ArgumentSchema(TypedDict, total=False):
    """The JSON schema of one argument; an ``object`` one is a schema model's, whose ``$ref``
    targets live in the tool's ``$defs``."""

    type: Required[str]
    description: str
    items: ArgumentSchema
    minimum: int
    maximum: int
    properties: dict[str, object]
    required: list[str]
    additionalProperties: bool


# A tool's arguments as a closed JSON schema object, with the definitions its object arguments
# refer to at the root, where ``#/$defs/...`` resolves (a ``$`` key needs the functional form).
InputSchema = TypedDict(
    "InputSchema",
    {
        "type": str,
        "properties": dict[str, ArgumentSchema],
        "required": list[str],
        "additionalProperties": bool,
        "$defs": NotRequired[dict[str, object]],
    },
)


def string_argument(description: str) -> ArgumentSchema:
    return {"type": "string", "description": description}


def object_schema(
    properties: dict[str, ArgumentSchema],
    *,
    required: list[str] | None = None,
    definitions: dict[str, object] | None = None,
) -> InputSchema:
    schema: InputSchema = {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }
    if definitions:
        schema["$defs"] = definitions
    return schema


def model_argument(
    model: type[BaseModel], description: str
) -> tuple[ArgumentSchema, dict[str, object]]:
    """A schema model as an object argument, in its field order (the order a model should write
    it in), and the definitions its ``$ref``s name, for the tool's ``$defs``."""
    schema = model.model_json_schema()
    argument: ArgumentSchema = {
        "type": "object",
        "description": description,
        "properties": schema["properties"],
        "required": schema.get("required", []),
        "additionalProperties": False,
    }
    definitions: dict[str, object] = schema.get("$defs", {})
    return argument, definitions


__all__ = [
    "ArgumentSchema",
    "InputSchema",
    "model_argument",
    "object_schema",
    "string_argument",
]
