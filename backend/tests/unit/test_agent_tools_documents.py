"""``read_loop`` and ``read_document`` on the fakes: the real LoopDocumentService, LoopService,
LoopNoteService, ListService and CardService on an in-memory board, handed to the tools as the
attributes ``LoopReading`` and ``DocumentReading`` declare."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, NotFound, ValidationFailure
from app.db.generated.board import LoopNotesRow
from app.services.agent_tools import read_document, read_loop
from app.services.agent_tools_documents import PAGE_CHARS
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loop_documents import LoopDocumentService
from app.services.loop_notes import LoopNoteService
from app.services.loop_plans import LoopPlanService
from app.services.loops import LoopService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    document_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
LOOP = "loop-a"
READER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)
ANALYSIS: dict[str, JsonValue] = {
    "outcome": "Know what to fix",
    "scope": ["docs"],
    "findings": [
        {"id": "F01", "title": "Wrong count", "category": "change", "technical_detail": "x" * 50},
        {"id": "F02", "title": "No glossary", "category": "risk", "technical_detail": "y"},
    ],
    "open_questions": ["Which language?"],
    "recommendation": "Fix F01 first.",
}
ROADMAP: dict[str, JsonValue] = {
    "summary": "Two steps",
    "phases": [
        {
            "id": "p1",
            "number": 1,
            "name": "Fix",
            "tickets": [
                {"id": "t1", "key": "L-1-PH01-001", "title": "Count", "summary": "Fixes it."},
                {"id": "t2", "key": "L-1-PH01-002", "title": "Glossary", "summary": ""},
            ],
        }
    ],
}


@dataclass(frozen=True, slots=True)
class DocumentWorld:
    """What both tools declare they use of the composition root, and the board."""

    loop_document: LoopDocumentService
    loop: LoopService
    loop_notes: LoopNoteService
    list: ListService
    card: CardService
    state: BoardState


def document_world(settings: Settings) -> DocumentWorld:
    """Loop L-1 with a three-line Info, a structured analysis_ai and roadmap_ai, a long human
    analysis, two Tickets in two columns and six notes, the oldest one long."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="analysis_review").__replace__(key="L-1")}
    state.lists = {
        "todo": list_row("todo", LOOP, 512, name="Todo"),
        "doing": list_row("doing", LOOP, 1024, name="Doing"),
    }
    state.cards = {
        "b": card_row("b", "doing", LOOP).__replace__(title="Second", position=1),
        "a": card_row("a", "todo", LOOP).__replace__(
            title="First", description="Long text.", summary="Short.", position=5
        ),
    }
    long_analysis = "\n".join(f"Line {n:04d} " + "-" * 40 for n in range(1, 2001))
    state.documents = [
        document_row("i1", LOOP, "info", content="Line one\nLine two\nLine three"),
        document_row("a1", LOOP, "analysis_ai", content="# Analysis").__replace__(
            payload_json=json.dumps(ANALYSIS)
        ),
        document_row("h1", LOOP, "analysis", content=long_analysis),
        document_row("r1", LOOP, "roadmap_ai", content="# RoadMap").__replace__(
            payload_json=json.dumps(ROADMAP)
        ),
    ]
    state.notes = [
        LoopNotesRow(
            id=f"n{index}",
            loop_id=LOOP,
            author_actor_id="agent-1",
            author_actor_type="agent",
            author_name="Reader",
            content=("long " * 200) if index == 1 else f"Note {index}",
            content_sha256=f"sha-{index}",
            created_at=f"2026-11-0{index}T10:00:00Z",
        )
        for index in range(1, 7)
    ]
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    views = plan_views(FakePlanViews(items=[]))
    cards = CardService(
        settings, checks, store, FakeRegistryUnitOfWork(RegistryState()), plans=views
    )
    plans = LoopPlanService(clock=lambda: NOW)
    return DocumentWorld(
        loop_document=LoopDocumentService(checks, store, plans, clock=lambda: NOW),
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        loop_notes=LoopNoteService(checks, store),
        list=ListService(checks, store),
        card=cards,
        state=state,
    )


def ask(**arguments: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, "loop_id": LOOP, **arguments}


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(_is_mapping(row) for row in value)


def section(answer: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = answer[key]
    assert _is_mapping(value)
    return value


def rows(answer: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = answer[key]
    assert _is_rows(value)
    return value


# --- read_loop -----------------------------------------------------------------------------------


def test_read_loop_is_an_overview_without_document_text(settings: Settings) -> None:
    answer = read_loop(document_world(settings), READER, ask())
    assert answer["loop"] == {
        "id": LOOP,
        "key": "L-1",
        "name": f"Loop {LOOP}",
        "goal": "",
        "stage": "analysis_review",
    }
    documents = section(answer, "documents")
    assert list(documents) == ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"]
    info = section(documents, "info")
    assert (info["revision_id"], info["revision_number"]) == ("i1", 1)
    assert (info["characters"], info["lines"]) == (28, 3)
    assert set(info) == {
        "state",
        "revision_id",
        "revision_number",
        "approved_revision_number",
        "characters",
        "lines",
        "provenance",
        "stale_reasons",
    }
    assert section(documents, "analysis")["lines"] == 2000
    assert section(documents, "roadmap")["revision_id"] is None
    assert "Line one" not in json.dumps(answer)
    assert len(json.dumps(answer)) < 5_000


def test_read_loop_lists_the_tickets_in_board_order_and_the_newest_notes_cut_short(
    settings: Settings,
) -> None:
    answer = read_loop(document_world(settings), READER, ask())
    tickets = rows(answer, "tickets")
    assert [(row["id"], row["column"], row["summary"]) for row in tickets] == [
        ("a", "Todo", "Short."),
        ("b", "Doing", ""),
    ]
    assert (answer["ticket_count"], answer["tickets_truncated"]) == (2, False)
    assert rows(answer, "columns") == [
        {"id": "todo", "name": "Todo", "tickets": 1},
        {"id": "doing", "name": "Doing", "tickets": 1},
    ]
    notes = rows(answer, "notes")
    assert [note["id"] for note in notes] == ["n2", "n3", "n4", "n5", "n6"]
    assert answer["note_count"] == 6
    assert all(note["truncated"] is False for note in notes)
    assert "read_document" in str(answer["next_step"])


def test_read_loop_cuts_a_long_note_and_refuses_document_kinds(settings: Settings) -> None:
    world = document_world(settings)
    world.state.notes = world.state.notes[:1]  # only the long one
    (note,) = rows(read_loop(world, READER, ask()), "notes")
    assert (len(str(note["content"])), note["truncated"]) == (500, True)
    with pytest.raises(ValidationFailure, match="read_document"):
        read_loop(world, READER, ask(document_kinds=["info"]))
    with pytest.raises(Forbidden):
        read_loop(world, READER.__replace__(scopes=frozenset()), ask())


# --- read_document -------------------------------------------------------------------------------


def test_read_document_answers_numbered_lines(settings: Settings) -> None:
    answer = read_document(document_world(settings), READER, ask(kind="info"))
    assert answer == {
        "kind": "info",
        "view": "text",
        "state": answer["state"],
        "revision_id": "i1",
        "revision_number": 1,
        "lines": "1-3 of 3",
        "text": "1\tLine one\n2\tLine two\n3\tLine three",
        "continue_from": None,
    }


def test_a_long_document_is_read_a_page_at_a_time_and_the_pages_join(settings: Settings) -> None:
    world = document_world(settings)
    first = read_document(world, READER, ask(kind="analysis"))
    assert len(str(first["text"])) <= PAGE_CHARS
    start = first["continue_from"]
    assert isinstance(start, int)
    second = read_document(world, READER, ask(kind="analysis", start_line=start))
    assert second["continue_from"] is None
    assert second["lines"] == f"{start}-2000 of 2000"
    joined = f"{first['text']}\n{second['text']}".splitlines()
    assert [line.split("\t", 1)[0] for line in joined] == [str(n) for n in range(1, 2001)]
    with pytest.raises(ValidationFailure, match="past the end"):
        read_document(world, READER, ask(kind="analysis", start_line=2001))


def test_the_structured_analysis_is_an_outline_and_one_finding_in_full(
    settings: Settings,
) -> None:
    world = document_world(settings)
    answer = read_document(world, READER, ask(kind="analysis_ai", view="structured"))
    outline = section(answer, "outline")
    assert outline["findings"] == [
        {"id": "F01", "title": "Wrong count", "category": "change"},
        {"id": "F02", "title": "No glossary", "category": "risk"},
    ]
    assert (outline["outcome"], outline["recommendation_characters"]) == ("Know what to fix", 14)
    assert section(outline, "counts")["scope"] == 1
    item = read_document(world, READER, ask(kind="analysis_ai", view="structured", item="F01"))
    assert section(item, "item")["technical_detail"] == "x" * 50
    with pytest.raises(NotFound) as caught:
        read_document(world, READER, ask(kind="analysis_ai", view="structured", item="F09"))
    assert caught.value.details == {"item": "F09", "items": ["F01", "F02"]}


def test_the_structured_roadmap_is_its_phases_and_tickets_and_one_of_them_in_full(
    settings: Settings,
) -> None:
    world = document_world(settings)
    answer = read_document(world, READER, ask(kind="roadmap_ai", view="structured"))
    assert section(answer, "outline") == {
        "summary": "Two steps",
        "phases": [
            {
                "id": "p1",
                "number": 1,
                "name": "Fix",
                "tickets": [
                    {"id": "t1", "key": "L-1-PH01-001", "title": "Count", "summary": "Fixes it."},
                    {"id": "t2", "key": "L-1-PH01-002", "title": "Glossary", "summary": ""},
                ],
            }
        ],
    }
    ticket = read_document(world, READER, ask(kind="roadmap_ai", view="structured", item="t2"))
    assert section(ticket, "item")["phase_id"] == "p1"
    phase = read_document(world, READER, ask(kind="roadmap_ai", view="structured", item="p1"))
    assert section(phase, "item")["name"] == "Fix"


def test_read_document_refuses_what_it_cannot_answer_and_says_when_a_document_is_empty(
    settings: Settings,
) -> None:
    world = document_world(settings)
    empty = read_document(world, READER, ask(kind="roadmap"))
    assert (empty["empty"], empty["revision_id"]) == (True, None)
    with pytest.raises(ValidationFailure, match="kind must be one of"):
        read_document(world, READER, ask(kind="notes"))
    with pytest.raises(ValidationFailure, match="view must be"):
        read_document(world, READER, ask(kind="info", view="json"))
    with pytest.raises(ValidationFailure, match="Only analysis_ai and roadmap_ai"):
        read_document(world, READER, ask(kind="info", view="structured"))
    with pytest.raises(Forbidden):
        read_document(world, READER.__replace__(scopes=frozenset()), ask(kind="info"))
