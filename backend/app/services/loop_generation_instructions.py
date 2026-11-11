"""The instructions a board agent works under, for a worker that writes the document itself, and
the id that holds the worker's document to them.

``read_instructions`` hands a worker, word for word, what the Loop's agent would get for an
analysis, a RoadMap or a brief for people (``LoopGenerationService.instructions``), and for a
document the board's repositories that agent reads. ``instructions_id`` is a fingerprint of
exactly that, and ``write_analysis``, ``write_roadmap`` and ``write_brief`` require the current
one (``check_instructions``), so every worker, whatever model it runs, writes under the same
instructions as a board agent: none hands a document in without having read them, and none hands
one in against instructions that have changed since.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, TypedDict

from ..core.errors import Conflict, ValidationFailure

if TYPE_CHECKING:  # annotations only: the repository service imports far more than this needs
    from .repositories import RepositoryEntry

# The purposes a worker may write itself, and so read the instructions of.
INSTRUCTION_PURPOSES = ("analysis", "analysis_human", "roadmap", "roadmap_human")
# A document's brief for people, which a worker writes with it.
BRIEF_PURPOSES = {"analysis": "analysis_human", "roadmap": "roadmap_human"}
INSTRUCTIONS_REQUIRED = "instructions_required"
INSTRUCTIONS_CHANGED = "instructions_changed"


class LinkedRepositories(Protocol):
    """``RepositoryService`` as the instructions read it: the board's enabled repositories with
    their links' globs, the ones a board agent reads."""

    def for_board(self, board_id: str) -> list[RepositoryEntry]: ...


class RepositoryCheck(TypedDict):
    """A repository a board agent reads, as a worker checks for it on its own machine."""

    name: str
    url: str
    branch: str | None
    last_read_commit: str | None
    focus_paths: list[str]
    exclude_paths: list[str]


class InstructionAgent(TypedDict):
    id: str
    name: str


class WritingInstructions(TypedDict):
    """What a board agent works under for one purpose in a Loop: the agent a run would use (None
    without a usable one), where its role comes from, the system prompt word for word, for an
    analysis or a RoadMap the system prompt of its brief for people too and the repositories it
    reads (None for a brief, which reads the document), for a RoadMap the approved faces its
    request shows, and the id a worker hands in with what it wrote to them."""

    purpose: str
    agent: InstructionAgent | None
    role_source: str | None
    instructions: str
    brief_instructions: str | None
    examples: str | None
    repositories: list[RepositoryCheck] | None
    instructions_id: str


def repository_checks(entries: Sequence[RepositoryEntry]) -> list[RepositoryCheck]:
    """The repositories a board agent reads, each with what a worker needs to find it locally."""
    return [
        {
            "name": entry["name"],
            "url": entry["url"],
            "branch": entry["branch"] or entry["default_branch"],
            "last_read_commit": entry.get("last_sha"),
            "focus_paths": entry.get("focus_paths", []),
            "exclude_paths": entry.get("exclude_paths", []),
        }
        for entry in entries
    ]


def instructions_id(
    purpose: str,
    instructions: str,
    brief_instructions: str | None,
    examples: str | None,
    repositories: Sequence[RepositoryCheck] | None,
) -> str:
    """A fingerprint of exactly what was handed out: the same instructions give the same id, and
    any change to the role, the rules, the schema, the examples or the repositories gives a new
    one. The commit Tralala read last is left out: a run in between moves it, while what the
    worker was told stays the same."""
    material = {
        "purpose": purpose,
        "instructions": instructions,
        "brief_instructions": brief_instructions,
        "examples": examples,
        "repositories": [
            {key: value for key, value in repository.items() if key != "last_read_commit"}
            for repository in repositories or ()
        ],
    }
    text = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def check_instructions(current: str, given: str | None, purpose: str) -> None:
    """A worker's document is written to the current instructions: ``422 instructions_required``
    without an id, ``409 instructions_changed`` with one that is not the current one (they
    changed since it was read, or it was never theirs)."""
    if not given:
        raise ValidationFailure(
            "instructions_id is required: read the instructions a board agent works under first "
            f"(read_instructions with purpose {purpose}) and hand in the instructions_id it "
            "answers",
            code=INSTRUCTIONS_REQUIRED,
            details={"argument": "instructions_id", "purpose": purpose},
        )
    if given != current:
        raise Conflict(
            "These are not the current instructions: they changed since they were read, or the "
            f"id is not theirs. Read them again (read_instructions with purpose {purpose}) and "
            "write to what it answers",
            code=INSTRUCTIONS_CHANGED,
            details={"argument": "instructions_id", "purpose": purpose},
        )


__all__ = [
    "BRIEF_PURPOSES",
    "INSTRUCTIONS_CHANGED",
    "INSTRUCTIONS_REQUIRED",
    "INSTRUCTION_PURPOSES",
    "InstructionAgent",
    "LinkedRepositories",
    "RepositoryCheck",
    "WritingInstructions",
    "check_instructions",
    "instructions_id",
    "repository_checks",
]
