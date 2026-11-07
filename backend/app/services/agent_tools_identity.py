"""``whoami``: what the calling key is and what it may do, in one call.

``tools/list`` already offers only the tools a key's scopes cover. ``whoami`` says the rest a worker
needs before it starts: which key it is and when that key expires, which scopes it holds and which
tools they open, which scopes a person's key could also hold and what each would open, and which
decisions no key can make. The tool list comes from the same filter as ``tools/list``, so the two
never disagree.

The handler is public and typed on the attribute of the composition root it uses, so a unit test
runs it with the real ``AuthService`` on the registry fakes. Its catalogue entry is built here too
(``identity_tools``) and placed first by ``agent_tools.tool_catalog``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..core.context import MEMBER_TOKEN_SCOPES, ActorContext
from .agent_tools_read import ToolArguments, ToolResult
from .agent_tools_schema import AgentTool, missing_scopes, object_schema

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .auth import AuthService

HUMAN_DECISIONS: tuple[str, ...] = (
    "approving analysis or a RoadMap",
    "resetting a scope",
    "editing Info",
    "confirming a human-only Ticket",
    "clearing a Ticket's wait",
    "accepting implementation or QA",
    "finalizing a Loop",
)
"""The decisions AGENTS.md rule 11a keeps for a signed-in person, in the rule's words; the
catalogue guard holds this tuple to its own list of them."""

_HUMAN_NOTE = (
    "A signed-in person makes these decisions; a key is refused with human_action_required "
    "whatever its scopes. Info stays yours to write while the Loop is draft or under analysis "
    "review; once planning has started, editing it is a person's."
)


class IdentityReading(Protocol):
    """What ``whoami`` uses of the composition root."""

    @property
    def auth(self) -> AuthService: ...


def _first_sentence(text: str) -> str:
    head, _, _ = text.partition(". ")
    return head.rstrip(".") + "."


def tools_and_gaps(actor: ActorContext, tools: list[AgentTool]) -> tuple[ToolResult, ToolResult]:
    """The tools the actor may call, and for every member scope it lacks, the tools that scope
    would open (a tool that also needs another missing scope is not counted)."""
    offered = [tool for tool in tools if not missing_scopes(tool, actor)]
    available: ToolResult = {tool.name: _first_sentence(tool.description) for tool in offered}
    gaps: ToolResult = {}
    for scope in MEMBER_TOKEN_SCOPES:
        if actor.has_scope(scope):
            continue
        opened = [
            tool.name
            for tool in tools
            if tool not in offered and set(missing_scopes(tool, actor)) == {scope}
        ]
        gaps[scope] = opened
    return available, gaps


def whoami(services: IdentityReading, actor: ActorContext, args: ToolArguments) -> ToolResult:
    actor.require("boards:read")
    del args  # whoami takes no arguments
    # Imported here: agent_tools builds its catalogue from this module's entry.
    from .agent_tools import tool_catalog

    available, gaps = tools_and_gaps(actor, list(tool_catalog().values()))
    return {
        "actor": {"id": actor.actor_id, "name": actor.actor_name, "type": actor.actor_type},
        "key": services.auth.current_key(actor),
        "scopes": sorted(actor.scopes),
        "tools": available,
        "missing_scopes": gaps,
        "human_only": {"decisions": list(HUMAN_DECISIONS), "note": _HUMAN_NOTE},
        "next_step": (
            "Call list_boards to find a board, then loop_summaries for where its Loops stand "
            "and list_tickets (with assignee me, a column, state or needs_person) for the Tickets "
            "to choose from. A scope you lack is granted by the person who issued this key, with "
            "a new key."
        ),
    }


def identity_tools() -> list[AgentTool]:
    """The catalogue entry of ``whoami``."""
    return [
        AgentTool(
            name="whoami",
            description=(
                "Say which key you are using and what it may do: the key's name, who issued it "
                "and when it expires, your scopes and the tools they open, the scopes you lack "
                "and what each would open, and the decisions only a person can make. Call it "
                "first."
            ),
            scopes=("boards:read",),
            input_schema=object_schema({}),
            handler=whoami,
        )
    ]


__all__ = ["HUMAN_DECISIONS", "IdentityReading", "identity_tools", "tools_and_gaps", "whoami"]
