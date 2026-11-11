"""What a board agent works under, read by a worker that writes the document itself:
``LoopGenerationService.instructions`` and the ``read_instructions`` tool. The instructions are the
system prompt a run composes, word for word, so a document handed in from outside is written to the
same text as one generated inside, and a RoadMap sees the same approved faces as examples. An
analysis or a RoadMap comes with its brief's instructions and the board's repositories with the
check a worker makes for them on its own machine. ``instructions_id`` fingerprints all of it, and
``require_instructions`` holds a worker's document to the current one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.services.agent_tools import tool_catalog
from app.services.agent_tools_plan import (
    CHECK_FIRST,
    HAND_IN,
    INSTRUCTIONS_NOTE,
    read_instructions,
)
from app.services.loop_generation import LoopGenerationService
from app.services.loop_generation_instructions import (
    BRIEF_PURPOSES,
    INSTRUCTION_PURPOSES,
    INSTRUCTIONS_CHANGED,
    INSTRUCTIONS_REQUIRED,
    instructions_id,
)
from app.services.loop_generation_prompts import FACE_EXAMPLES_HEADING, compose_system_prompt
from app.services.repositories import RepositoryEntry
from tests.unit.fakes.board import BOARD_ID
from tests.unit.test_loop_generation_face import board_with_approvals
from tests.unit.test_loop_generation_service import ADA, LOOP, STAMP, make, start

READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)
# The board's enabled repositories with their links' globs, as RepositoryService.for_board
# answers them: one on its default branch, read before, one on a branch of its own, never read.
LINKED: list[RepositoryEntry] = [
    {
        "id": "repo-1",
        "name": "tralala",
        "provider": "git_https",
        "url": "https://git.example/tralala.git",
        "branch": None,
        "default_branch": "master",
        "enabled": True,
        "created_at": STAMP,
        "updated_at": STAMP,
        "has_token": False,
        "boards": [],
        "last_sha": "f163bb9",
        "focus_paths": [],
        "exclude_paths": [".claude/**", "docs/**"],
    },
    {
        "id": "repo-2",
        "name": "site",
        "provider": "github",
        "url": "https://github.com/example/site",
        "branch": "main",
        "default_branch": "master",
        "enabled": True,
        "created_at": STAMP,
        "updated_at": STAMP,
        "has_token": False,
        "boards": [],
    },
]


@dataclass
class Linked:
    """RepositoryService as the instructions read it, recording the boards it was asked for."""

    entries: list[RepositoryEntry]
    asked: list[str] = field(default_factory=list[str])

    def for_board(self, board_id: str) -> list[RepositoryEntry]:
        self.asked.append(board_id)
        return self.entries


@dataclass(frozen=True, slots=True)
class Composition:
    """What read_instructions uses of the composition root."""

    loop_generation: LoopGenerationService


def args(purpose: str) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "loop_id": LOOP, "purpose": purpose}


# --- the instructions ----------------------------------------------------------------------------


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


def test_a_document_comes_with_its_briefs_instructions_and_a_brief_with_none() -> None:
    w = make()
    for document, brief in BRIEF_PURPOSES.items():
        view = w.service.instructions(ADA, BOARD_ID, LOOP, document)
        assert view["brief_instructions"] == compose_system_prompt(brief, "You are alpha.")
        assert w.service.instructions(ADA, BOARD_ID, LOOP, brief)["brief_instructions"] is None
    # Without a usable agent the brief's rules and schema still stand, without a role.
    bare = make(agents=("off",)).service.instructions(ADA, BOARD_ID, LOOP, "roadmap")
    assert bare["brief_instructions"] == compose_system_prompt("roadmap_human", "")


def test_a_document_lists_the_repositories_a_board_agent_reads_and_a_brief_none() -> None:
    linked = Linked(LINKED)
    w = make(linked=linked)
    assert w.service.instructions(ADA, BOARD_ID, LOOP, "analysis")["repositories"] == [
        {
            "name": "tralala",
            "url": "https://git.example/tralala.git",
            "branch": "master",
            "last_read_commit": "f163bb9",
            "focus_paths": [],
            "exclude_paths": [".claude/**", "docs/**"],
        },
        {
            "name": "site",
            "url": "https://github.com/example/site",
            "branch": "main",
            "last_read_commit": None,
            "focus_paths": [],
            "exclude_paths": [],
        },
    ]
    assert linked.asked == [BOARD_ID]
    for brief in BRIEF_PURPOSES.values():
        assert w.service.instructions(ADA, BOARD_ID, LOOP, brief)["repositories"] is None
    assert linked.asked == [BOARD_ID]
    # Without the repository service (generation tests), a document lists none.
    assert make().service.instructions(ADA, BOARD_ID, LOOP, "roadmap")["repositories"] == []


# --- the id that holds a worker's document to them -----------------------------------------------


def test_the_id_follows_what_was_handed_out_and_nothing_else() -> None:
    linked = Linked(list(LINKED))
    w = make(linked=linked)

    def current(purpose: str = "analysis") -> str:
        return w.service.instructions(ADA, BOARD_ID, LOOP, purpose)["instructions_id"]

    first = current()
    assert current() == first
    # Each purpose has its own instructions, and so its own id.
    assert current("roadmap") != first
    # A run that reads the repository again moves the commit; the instructions stay the same.
    moved = LINKED[0].copy()
    moved["last_sha"] = "913abb2"
    linked.entries[0] = moved
    assert current() == first
    # A changed glob changes what a board agent reads, and so the id.
    narrowed = LINKED[0].copy()
    narrowed["exclude_paths"] = [".claude/**"]
    linked.entries[0] = narrowed
    assert current() != first
    # Another agent's role is other instructions.
    other = make(linked=Linked(LINKED), preferences={"analysis": "beta"})
    assert other.service.instructions(ADA, BOARD_ID, LOOP, "analysis")["instructions_id"] != first


def test_the_id_is_a_fingerprint_of_its_parts() -> None:
    base = instructions_id("analysis", "rules", "brief rules", None, [])
    assert base == instructions_id("analysis", "rules", "brief rules", None, [])
    assert len(base) == 16
    for changed in (
        instructions_id("roadmap", "rules", "brief rules", None, []),
        instructions_id("analysis", "other rules", "brief rules", None, []),
        instructions_id("analysis", "rules", None, None, []),
        instructions_id("analysis", "rules", "brief rules", "Examples", []),
    ):
        assert changed != base


def test_a_worker_hands_in_the_current_id_or_its_document_is_refused() -> None:
    w = make(linked=Linked(LINKED))
    current = w.service.instructions(ADA, BOARD_ID, LOOP, "roadmap")["instructions_id"]
    assert w.service.require_instructions(ADA, BOARD_ID, LOOP, "roadmap", current) == current
    with pytest.raises(ValidationFailure) as missing:
        w.service.require_instructions(ADA, BOARD_ID, LOOP, "roadmap", None)
    assert missing.value.code == INSTRUCTIONS_REQUIRED
    assert missing.value.details == {"argument": "instructions_id", "purpose": "roadmap"}
    assert "read_instructions with purpose roadmap" in missing.value.message
    with pytest.raises(Conflict) as changed:
        w.service.require_instructions(ADA, BOARD_ID, LOOP, "roadmap", "0123456789abcdef")
    assert changed.value.code == INSTRUCTIONS_CHANGED
    # The analysis's id is not the RoadMap's.
    analysis = w.service.instructions(ADA, BOARD_ID, LOOP, "analysis")["instructions_id"]
    with pytest.raises(Conflict):
        w.service.require_instructions(ADA, BOARD_ID, LOOP, "roadmap", analysis)


# --- the tool ------------------------------------------------------------------------------------


def test_read_instructions_answers_them_with_how_to_use_them_and_where_they_go() -> None:
    w = make()
    answer = read_instructions(Composition(w.service), ADA, args("roadmap"))
    assert answer["instructions"] == compose_system_prompt("roadmap", "You are alpha.")
    assert (answer["how_to_use"], answer["hand_in"]) == (INSTRUCTIONS_NOTE, HAND_IN["roadmap"])
    assert "brief_instructions" in str(answer["hand_in"])
    assert "instructions_id" in INSTRUCTIONS_NOTE
    assert answer["instructions_id"] == w.service.instructions(ADA, BOARD_ID, LOOP, "roadmap")[
        "instructions_id"
    ]
    assert set(HAND_IN) == set(INSTRUCTION_PURPOSES)
    tool = tool_catalog()["read_instructions"]
    assert (tool.scopes, tool.handler) == (("loops:generate",), read_instructions)


def test_a_document_starts_with_the_repositories_to_check_and_a_brief_reads_none() -> None:
    w = make(linked=Linked(LINKED))
    answer = read_instructions(Composition(w.service), ADA, args("analysis"))
    assert list(answer)[:2] == ["check_first", "repositories"]
    assert answer["check_first"] == CHECK_FIRST
    listed = w.service.instructions(ADA, BOARD_ID, LOOP, "analysis")["repositories"]
    assert answer["repositories"] == listed
    assert listed is not None
    assert [repository["name"] for repository in listed] == ["tralala", "site"]
    # The check says what to do when a repository is not on the worker's machine.
    assert "not downloaded here" in CHECK_FIRST
    assert "open_questions" in CHECK_FIRST
    for brief in BRIEF_PURPOSES.values():
        answer = read_instructions(Composition(w.service), ADA, args(brief))
        assert "check_first" not in answer
        assert "repositories" not in answer


def test_the_write_tools_and_the_bootstrap_point_at_the_instructions(settings: Settings) -> None:
    catalog = tool_catalog()
    for name in ("write_analysis", "write_roadmap", "write_brief"):
        assert "read_instructions" in catalog[name].description
        assert "instructions_id" in catalog[name].input_schema.get("required", [])
    bootstrap = render_bootstrap(settings)
    assert "### read_instructions (requires `loops:generate`)" in bootstrap
    rules = bootstrap.split("## 4. ", 1)[1].split("\n## 5. ", 1)[0]
    assert "(`read_instructions`)" in rules
    # /llms.txt marks what the write tools require as required, not optional.
    for name in ("write_analysis", "write_roadmap"):
        section = bootstrap.split(f"### {name} (", 1)[1].split("\n### ", 1)[0]
        assert "- `brief` (required): " in section
        assert "- `instructions_id` (required): " in section
