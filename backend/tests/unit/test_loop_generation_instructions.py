"""What a board agent works under, read by a worker that writes the document itself:
``LoopGenerationService.instructions`` and the ``read_instructions`` tool. The instructions are the
system prompt a run composes, word for word, so a document handed in from outside is written to the
same text as one generated inside, and a RoadMap sees the same approved faces as examples.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.api.mcp import render_bootstrap
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.services.agent_tools import tool_catalog
from app.services.agent_tools_plan import HAND_IN, INSTRUCTIONS_NOTE, read_instructions
from app.services.loop_generation import LoopGenerationService
from app.services.loop_generation_prompts import (
    FACE_EXAMPLES_HEADING,
    INSTRUCTION_PURPOSES,
    compose_system_prompt,
)
from tests.unit.fakes.board import BOARD_ID
from tests.unit.test_loop_generation_face import board_with_approvals
from tests.unit.test_loop_generation_service import ADA, LOOP, make, start

READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)


@dataclass(frozen=True, slots=True)
class Composition:
    """What read_instructions uses of the composition root."""

    loop_generation: LoopGenerationService


@pytest.mark.parametrize("purpose", INSTRUCTION_PURPOSES)
def test_the_instructions_are_what_the_loops_agent_works_under(purpose: str) -> None:
    w = make()
    view = w.service.instructions(ADA, BOARD_ID, LOOP, purpose)
    assert (view["purpose"], view["agent"], view["role_source"]) == (
        purpose,
        {"id": "alpha", "name": "Alpha"},
        "template",
    )
    assert view["instructions"] == compose_system_prompt(purpose, "You are alpha.")


def test_the_instructions_are_the_system_prompt_a_run_stores() -> None:
    w = make()
    start(w)
    stored = json.loads(w.run().role_snapshot_json)["system_prompt"]
    assert w.service.instructions(ADA, BOARD_ID, LOOP, "analysis")["instructions"] == stored


def test_a_brief_comes_from_the_agent_the_loop_prefers_for_its_document() -> None:
    w = make(preferences={"analysis": "beta", "roadmap": "alpha"})
    for purpose, agent in (
        ("analysis", "beta"),
        ("analysis_human", "beta"),
        ("roadmap", "alpha"),
        ("roadmap_human", "alpha"),
    ):
        view = w.service.instructions(ADA, BOARD_ID, LOOP, purpose)
        assert view["agent"] is not None
        assert view["agent"]["id"] == agent
        assert view["instructions"].startswith(f"You are {agent}.\n\n")


def test_without_a_usable_agent_the_rules_and_the_schema_still_stand() -> None:
    w = make(agents=("off", "org", "legacy"))
    view = w.service.instructions(ADA, BOARD_ID, LOOP, "analysis")
    assert (view["agent"], view["role_source"]) == (None, None)
    assert view["instructions"] == compose_system_prompt("analysis", "")


def test_a_roadmap_shows_the_faces_the_owner_approved_last() -> None:
    w = make()
    board_with_approvals(w.state)
    examples = w.service.instructions(ADA, BOARD_ID, LOOP, "roadmap")["examples"]
    assert examples is not None
    assert examples.startswith(FACE_EXAMPLES_HEADING)
    assert examples.index("Show the early button") < examples.index("Show the late column")
    for purpose in ("analysis", "analysis_human", "roadmap_human"):
        assert w.service.instructions(ADA, BOARD_ID, LOOP, purpose)["examples"] is None
    # A board without an approved face has no example to show.
    assert make().service.instructions(ADA, BOARD_ID, LOOP, "roadmap")["examples"] is None


def test_an_unknown_purpose_a_missing_loop_and_a_reader_are_refused() -> None:
    w = make()
    with pytest.raises(ValidationFailure) as unknown:
        w.service.instructions(ADA, BOARD_ID, LOOP, "qa")
    assert unknown.value.details == {"argument": "purpose", "allowed": list(INSTRUCTION_PURPOSES)}
    with pytest.raises(NotFound) as missing:
        w.service.instructions(ADA, BOARD_ID, "ghost", "analysis")
    assert missing.value.code == "loop_not_found"
    with pytest.raises(Forbidden):
        w.service.instructions(READER, BOARD_ID, LOOP, "analysis")


def test_read_instructions_answers_them_with_how_to_use_them_and_where_they_go() -> None:
    w = make()
    answer = read_instructions(
        Composition(w.service), ADA, {"board_id": BOARD_ID, "loop_id": LOOP, "purpose": "roadmap"}
    )
    assert answer["instructions"] == compose_system_prompt("roadmap", "You are alpha.")
    assert (answer["how_to_use"], answer["hand_in"]) == (INSTRUCTIONS_NOTE, HAND_IN["roadmap"])
    assert set(HAND_IN) == set(INSTRUCTION_PURPOSES)
    tool = tool_catalog()["read_instructions"]
    assert (tool.scopes, tool.handler) == (("loops:generate",), read_instructions)


def test_the_write_tools_and_the_bootstrap_point_at_the_instructions(settings: Settings) -> None:
    catalog = tool_catalog()
    for name in ("write_analysis", "write_roadmap", "write_brief"):
        assert "read_instructions" in catalog[name].description
    bootstrap = render_bootstrap(settings)
    assert "### read_instructions (requires `loops:generate`)" in bootstrap
    rules = bootstrap.split("## 4. ", 1)[1].split("\n## 5. ", 1)[0]
    assert "(`read_instructions`)" in rules
