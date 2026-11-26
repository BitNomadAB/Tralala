"""The JSON schemas of the worker catalogue's arguments, as ``tools/list`` serves them.

``agent_tools`` builds each entry's ``inputSchema`` with these helpers; they hold no rule of their
own, only the shape MCP and ``/llms.txt`` read.

Beside them are the catalogue entry itself (``AgentTool``) and what a tool that asks the client
for input exchanges with the transport: the client's answers it is given (``ToolInput``) and the
question it may answer with instead of a result (``InputRequired``). Only ``ask_person`` asks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

from pydantic import BaseModel, JsonValue

from ..core.context import ActorContext
from .agent_tools_read import ToolArguments, ToolResult

if TYPE_CHECKING:  # the composition root imports the catalogue lazily, so keep the cycle out
    from . import Services


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

@dataclass(frozen=True, slots=True)
class ToolInput:
    """What a ``tools/call`` of MCP 2026-07-28 brings a tool that asks for input: the
    elicitation modes its client declared, a retry's answers (``inputResponses``) and the opaque
    state the tool answered with before (``requestState``), which is attacker-controlled until
    the tool's service has opened it. A call that brings none of it (a client of 2025-06-18, or
    REST) is ``NO_INPUT``."""

    form: bool = False
    url: bool = False
    responses: Mapping[str, Mapping[str, JsonValue]] = field(
        default_factory=dict[str, Mapping[str, JsonValue]]
    )
    request_state: str | None = None


NO_INPUT = ToolInput()


@dataclass(frozen=True, slots=True)
class InputRequired:
    """A tool's answer that asks the client for input before it can complete: the requests
    (``inputRequests``, keyed by the tool) and the sealed state the client repeats the call with
    (``requestState``). The transport makes it a result with ``resultType`` ``input_required``."""

    input_requests: Mapping[str, Mapping[str, object]]
    request_state: str


type AskingHandler = Callable[
    [Services, ActorContext, ToolArguments, ToolInput], ToolResult | InputRequired
]


@dataclass(frozen=True, slots=True)
class AgentTool:
    """One callable capability: wire contract plus the handler that runs it.

    ``asks`` is set only on a tool that may ask the client for input: the transport of MCP
    2026-07-28 runs it instead of ``handler`` and gives it the call's ``ToolInput``. ``handler``
    stays the tool's answer for every other caller, as if the client could be asked nothing.
    """

    name: str
    description: str
    scopes: tuple[str, ...]
    input_schema: InputSchema
    handler: Callable[[Services, ActorContext, ToolArguments], ToolResult]
    asks: AskingHandler | None = None


def missing_scopes(tool: AgentTool, actor: ActorContext) -> tuple[str, ...]:
    """Scopes the tool needs that the actor does not hold; empty means it may run."""
    return tuple(scope for scope in tool.scopes if not actor.has_scope(scope))


def describe_scope(tool: AgentTool) -> str:
    return "Requires " + ", ".join(f"`{scope}`" for scope in tool.scopes) + "."


__all__ = [
    "NO_INPUT",
    "AgentTool",
    "ArgumentSchema",
    "AskingHandler",
    "InputRequired",
    "InputSchema",
    "ToolInput",
    "describe_scope",
    "missing_scopes",
    "model_argument",
    "object_schema",
    "string_argument",
]
