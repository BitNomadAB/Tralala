"""``loop_summaries`` on the fakes: the real LoopService, ListService and CardService on an
in-memory board, handed to the tool as the attributes ``LoopSummarising`` declares; what each Loop's
row says comes next and who does it, the address of the decision a person takes next, and which
Tickets the key has not reported on."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.db.generated.board import CardsRow, LoopDocumentsRow, LoopsRow
from app.schemas.poc_decisions import PocDecisionAnswerCreate, PocDecisionCreate
from app.services.agent_tools import ToolResult, loop_summaries, tool_catalog
from app.services.agent_tools_loops import ALL_DONE, ALL_DONE_WITHOUT_PLAN, ticket_counts
from app.services.agent_tools_read import REPORT_FIRST
from app.services.cards import CardService
from app.services.lists import ListService
from app.services.loops import LoopService
from app.services.plan_views import LoopReadiness, ReadinessItem
from app.services.poc_decisions import PocDecisionService
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    activity_row,
    card_row,
    comment_row,
    document_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import (
    BLOCKER,
    CONFIRMATION,
    FakePlanViews,
    plan_views,
    readiness_item,
)
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
READER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Reader", scopes=frozenset({"loops:read"})
)
# An issued key: an agent with a credential, the actor 409 report_required refuses.
KEY = ActorContext(
    actor_id="key-1",
    actor_type="agent",
    actor_name="Key",
    scopes=frozenset({"loops:read"}),
    credential_id="cred-1",
)
MOVED = "2026-11-25T20:35:03Z"
LATER = "2026-11-25T20:40:00Z"
PUBLIC = "https://tralala.example.com"


def uid(n: int) -> str:
    """A Loop's id as its row has it, a UUID: the address of a decision is built from it."""
    return f"00000000-0000-4000-8000-{n:012d}"


@dataclass(frozen=True, slots=True)
class LoopWorld:
    """What ``loop_summaries`` declares it uses of the composition root, and the board."""

    loop: LoopService
    list: ListService
    card: CardService
    settings: Settings
    poc_decisions: PocDecisionService
    state: BoardState


def loop_world(
    settings: Settings,
    loops: list[LoopsRow],
    *,
    items: list[ReadinessItem] | None = None,
    state: BoardState | None = None,
    public_url: str | None = None,
) -> LoopWorld:
    """The Loops given, each with a Todo and a Doing column; every Loop answers ``items`` as its
    planned Tickets' readiness. ``public_url`` is the installation's public address: unset unless
    given, whatever the environment says."""
    board = state or BoardState()
    board.loops = {loop.id: loop for loop in loops}
    for loop in loops:
        board.lists[f"todo-{loop.id}"] = list_row(f"todo-{loop.id}", loop.id, 512, name="Todo")
        board.lists[f"doing-{loop.id}"] = list_row(f"doing-{loop.id}", loop.id, 1024, name="Doing")
    views = plan_views(FakePlanViews(items=items or []))
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(board)
    cards = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(RegistryState()),
        plans=views,
        clock=lambda: NOW,
    )
    return LoopWorld(
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        list=ListService(checks, store),
        card=cards,
        settings=settings.model_copy(update={"public_url": public_url}),
        poc_decisions=PocDecisionService(checks, store, cards, plans=views, clock=lambda: NOW),
        state=board,
    )


def loop(loop_id: str, stage: str, sequence: int, *, goal: str = "") -> LoopsRow:
    completed = CREATED if stage == "completed" else None
    return loop_row(loop_id, stage=stage, completed_at=completed).__replace__(
        sequence=sequence, key=f"L-{sequence}", goal=goal
    )


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_rows(value: object) -> TypeIs[list[Mapping[str, object]]]:
    return _is_list(value) and all(isinstance(row, Mapping) for row in value)


def rows(answer: ToolResult) -> list[Mapping[str, object]]:
    value = answer["loops"]
    assert _is_rows(value)
    return value


def ask(**arguments: JsonValue) -> dict[str, JsonValue]:
    return {"board_id": BOARD_ID, **arguments}


def done(item: ReadinessItem) -> ReadinessItem:
    item["completed_at"] = CREATED
    item["state"] = None
    return item


# --- the rows ------------------------------------------------------------------------------------


def test_each_open_loop_says_what_comes_next_and_who_does_it(settings: Settings) -> None:
    review = uid(2)
    state = BoardState()
    state.documents = [
        document_row("i2", review, "info", content="Why"),
        document_row("a2", review, "analysis_ai", status="ready_for_review", revision=3, info="i2"),
    ]
    world = loop_world(
        settings,
        [
            loop("draft", "draft", 1, goal="Know  what\nto fix " + "x" * 300),
            loop(review, "analysis_review", 2),
            loop("plan", "planning", 3),
            loop("old", "completed", 4),
        ],
        state=state,
    )
    answer = loop_summaries(world, READER, ask())
    draft, review, plan = rows(answer)
    assert answer["count"] == 3
    assert (draft["key"], draft["stage"], draft["waiting_on"]) == ("L-1", "draft", "person")
    assert draft["next"] == (
        "Write the Loop's Info for the planned path, or add a Ticket (create_ticket) for a small "
        "change without a plan."
    )
    assert str(draft["goal"]).startswith("Know what to fix x")
    assert len(str(draft["goal"])) == 280
    assert (review["waiting_on"], review["next"]) == (
        "person",
        "A person reviews the analysis and approves it or asks for changes.",
    )
    documents = review["documents"]
    assert isinstance(documents, Mapping)
    assert (documents["analysis_ai"], documents["info"], documents["roadmap"]) == (
        "ready_for_review r3",
        "draft r1",
        "empty",
    )
    assert (plan["waiting_on"], "hand one in" in str(plan["next"])) == ("agent", True)
    assert "list_tickets" in str(answer["next_step"])
    finished = rows(loop_summaries(world, READER, ask(include_completed=True)))[-1]
    assert (finished["key"], finished["waiting_on"]) == ("L-4", "nobody")
    assert "read-only" in str(finished["next"])


def test_a_loop_in_delivery_counts_its_tickets_by_state(settings: Settings) -> None:
    state = BoardState()
    state.cards = {
        "a": card_row("a", "todo-run", "run"),
        "b": card_row("b", "todo-run", "run"),
        "c": card_row("c", "doing-run", "run"),
        # Outside the plan: only its own wait holds it up (a third party: blocked).
        "u": card_row("u", "doing-run", "run").__replace__(
            kind="manual", ticket_key="L-1-UNP-001", waiting_for="third_party"
        ),
    }
    items = [
        readiness_item("x", ready=False, waiting_for="decision"),
        readiness_item("a"),
        readiness_item("b", human=True),
        readiness_item("c", ready=False),
        done(readiness_item("d")),
    ]
    world = loop_world(
        settings,
        [loop("run", "ready", 1).__replace__(current_plan_id="plan-1")],
        items=items,
        state=state,
    )
    (row,) = rows(loop_summaries(world, READER, ask()))
    # needs_input beats blocked, and a person answers it first.
    assert (row["next"], row["waiting_on"], row["execution_allowed"]) == (
        "1 Ticket waits for a person's decision, information or access.",
        "person",
        True,
    )
    assert row["tickets"] == {
        "ready": 2,
        "needs_input": 1,
        "blocked": 2,
        "not_done": 0,
        "completed": 1,
        "total": 6,
        "needs_person": 2,
        "awaiting_confirmation": 0,
        "by_column": {"Todo": 2, "Doing": 2},
    }
    ready = loop_world(settings, [loop("run", "ready", 1)], items=items[1:])
    (row,) = rows(loop_summaries(ready, READER, ask()))
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready to start.", "anyone")
    person_only = loop_world(settings, [loop("run", "in_progress", 1)], items=items[2:])
    (row,) = rows(loop_summaries(person_only, READER, ask()))
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready and needs a person.", "person")
    waiting = loop_world(settings, [loop("run", "ready", 1)], items=items[3:])
    (row,) = rows(loop_summaries(waiting, READER, ask()))
    assert (row["next"], row["waiting_on"]) == (
        "1 Ticket waits for earlier work or a third party.",
        "anyone",
    )
    # A Loop with a plan whose Tickets are all done goes on to the acceptance and its QA.
    finished = loop_world(
        settings,
        [loop(uid(1), "ready", 1).__replace__(current_plan_id="plan-1")],
        items=items[4:],
    )
    (row,) = rows(loop_summaries(finished, READER, ask()))
    assert row["without_plan"] is False
    assert (row["waiting_on"], "accepts the implementation" in str(row["next"])) == ("person", True)


def test_a_completed_loop_counts_what_was_never_done_as_not_done(settings: Settings) -> None:
    state = BoardState()
    state.cards = {
        # Left open when the Loop was completed, one of them waiting for an answer then.
        "u": card_row("u", "doing-run", "run").__replace__(
            kind="manual", ticket_key="L-1-UNP-001", waiting_for="decision"
        ),
        "v": card_row("v", "doing-run", "run").__replace__(
            kind="manual", ticket_key="L-1-UNP-002", completed_at=CREATED
        ),
    }
    world = loop_world(
        settings,
        [loop("run", "completed", 1).__replace__(current_plan_id="plan-1")],
        state=state,
    )
    (row,) = rows(loop_summaries(world, READER, ask(include_completed=True)))
    assert row["waiting_on"] == "nobody"
    # Nothing in a completed Loop waits for a person, and nothing in it is ready to start.
    assert row["tickets"] == {
        "ready": 0,
        "needs_input": 0,
        "blocked": 0,
        "not_done": 1,
        "completed": 1,
        "total": 2,
        "needs_person": 0,
        "awaiting_confirmation": 0,
        "by_column": {"Todo": 0, "Doing": 2},
    }


def test_a_loop_without_a_plan_counts_its_tickets_as_its_work(settings: Settings) -> None:
    state = BoardState()
    state.cards = {
        "u": card_row("u", "todo-solo", "solo").__replace__(
            kind="manual", ticket_key="L-1-UNP-001"
        ),
        "v": card_row("v", "doing-solo", "solo").__replace__(
            kind="manual", ticket_key="L-1-UNP-002", completed_at=CREATED
        ),
    }
    world = loop_world(settings, [loop("solo", "in_progress", 1)], state=state)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["without_plan"], row["execution_allowed"]) == (True, True)
    assert row["tickets"] == {
        "ready": 1,
        "needs_input": 0,
        "blocked": 0,
        "not_done": 0,
        "completed": 1,
        "total": 2,
        "needs_person": 0,
        "awaiting_confirmation": 0,
        "by_column": {"Todo": 1, "Doing": 1},
    }
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready to start.", "anyone")


def test_a_row_says_whether_the_loop_runs_without_a_plan(settings: Settings) -> None:
    world = loop_world(
        settings,
        [
            loop(uid(1), "in_progress", 1),
            loop(uid(2), "in_progress", 2).__replace__(current_plan_id="plan-1"),
            loop("draft", "draft", 3),
        ],
    )
    answer = rows(loop_summaries(world, READER, ask()))
    assert [(row["key"], row["without_plan"]) for row in answer] == [
        ("L-1", True),
        ("L-2", False),
        ("L-3", False),
    ]


def test_a_draft_with_its_info_offers_the_analysis_or_a_ticket_without_a_plan(
    settings: Settings,
) -> None:
    state = BoardState()
    state.documents = [document_row("i1", "draft", "info", content="Why")]
    world = loop_world(settings, [loop("draft", "draft", 1)], state=state)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["next"], row["waiting_on"]) == (
        "Ask for the analysis (run_analysis) or hand one in, written to a board agent's "
        "instructions (read_instructions, then write_analysis); or add a Ticket (create_ticket) "
        "for a small change without a plan.",
        "agent",
    )


def test_a_loop_without_a_plan_whose_tickets_are_done_waits_for_a_person_to_close_it(
    settings: Settings,
) -> None:
    solo = uid(6)
    state = BoardState()
    state.cards = {
        "u": card_row("u", f"doing-{solo}", solo).__replace__(
            kind="manual", ticket_key="L-1-UNP-001", completed_at=CREATED
        ),
        # Archived before it was done: it neither counts nor holds the Loop up.
        "v": card_row("v", f"todo-{solo}", solo).__replace__(
            kind="manual", ticket_key="L-1-UNP-002", archived_at=CREATED
        ),
    }
    world = loop_world(settings, [loop(solo, "in_progress", 1)], state=state)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert row["without_plan"] is True
    assert (row["next"], row["waiting_on"]) == (ALL_DONE_WITHOUT_PLAN, "person")
    tickets = row["tickets"]
    assert isinstance(tickets, Mapping)
    assert (tickets["completed"], tickets["total"]) == (1, 1)


def test_work_awaiting_a_person_s_confirmation_is_ready_or_done_and_counted(
    settings: Settings,
) -> None:
    def held(card_id: str) -> ReadinessItem:
        return readiness_item(
            card_id, ready=False, blockers=(BLOCKER,), confirmations=(CONFIRMATION,)
        )

    items = [readiness_item("first", human=True), held("open"), done(held("done"))]
    readiness: LoopReadiness = {
        "loop_id": "run",
        "stage": "in_progress",
        "execution_allowed": True,
        "blocked_reason": None,
        "items": items,
        "phases": [],
        "unplanned": [],
        "open_delivery": [],
    }
    counts = ticket_counts(readiness)
    assert (counts.ready, counts.blocked, counts.completed) == (2, 0, 1)
    assert (counts.awaiting_confirmation, counts.needs_person) == (1, 1)
    world = loop_world(settings, [loop("run", "in_progress", 1)], items=items)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["next"], row["waiting_on"]) == ("1 Ticket is ready to start.", "anyone")
    # Once the open one is done too, the person's task is what is left, and the sentence says the
    # done work awaits it.
    items[1] = done(held("open"))
    world = loop_world(settings, [loop("run", "in_progress", 1)], items=items)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["next"], row["waiting_on"]) == (
        "1 Ticket is ready and needs a person. 2 Tickets are done and await that confirmation.",
        "person",
    )


def test_no_ticket_count_or_ticket_sentence_names_an_agent(settings: Settings) -> None:
    """A person owns every Ticket: delivery never waits on an agent, and no count says one does
    the work; only a document may wait on an agent (decision support)."""
    for items in (
        [readiness_item("a")],
        [readiness_item("b", human=True)],
        [readiness_item("c", ready=False)],
        [readiness_item("x", waiting_for="access")],
    ):
        world = loop_world(settings, [loop("run", "in_progress", 1)], items=items)
        (row,) = rows(loop_summaries(world, READER, ask()))
        assert row["waiting_on"] in {"person", "anyone"}
        assert "agent" not in str(row["next"]).casefold()
        tickets = row["tickets"]
        assert isinstance(tickets, Mapping)
        assert "ready_for_agent" not in tickets
        assert "ready_for_person" not in tickets


def test_loop_summaries_narrows_to_a_stage_and_refuses_an_unknown_one(settings: Settings) -> None:
    world = loop_world(
        settings,
        [loop("draft", "draft", 1), loop("plan", "planning", 2), loop("old", "completed", 3)],
    )
    assert [row["key"] for row in rows(loop_summaries(world, READER, ask(stage="planning")))] == [
        "L-2"
    ]
    # Naming a finished stage lists finished Loops without include_completed.
    assert [row["key"] for row in rows(loop_summaries(world, READER, ask(stage="completed")))] == [
        "L-3"
    ]
    with pytest.raises(ValidationFailure, match="stage must be one of"):
        loop_summaries(world, READER, ask(stage="shipping"))
    with pytest.raises(Forbidden):
        loop_summaries(world, READER.__replace__(scopes=frozenset({"cards:read"})), ask())


# --- the address of the decision a person takes next ---------------------------------------------


def decisions_world(settings: Settings, *, public_url: str | None = None) -> LoopWorld:
    """A Loop for each decision a person takes next, and one for each next step that is no single
    decision of the Loop. Every Loop answers one planned Ticket, done.

    L-1 reviews its analysis, L-2 its RoadMap, L-3 awaits QA; every Ticket of L-4 (planned) and of
    L-5 (without a plan) is done. L-6 is a draft without Info, L-7's analysis is out of date with
    its Info, L-8 has a Ticket ready to start and L-9 a Ticket that waits for a person's answer.
    """
    state = BoardState()
    state.documents = [
        document_row("i1", uid(1), "info"),
        document_row("a1", uid(1), "analysis_ai", status="ready_for_review", info="i1"),
        document_row("i2", uid(2), "info"),
        document_row("a2", uid(2), "analysis_ai", status="approved", info="i2"),
        document_row("h2", uid(2), "analysis", status="approved", analysis_ai="a2"),
        document_row(
            "r2",
            uid(2),
            "roadmap_ai",
            status="ready_for_review",
            info="i2",
            analysis_ai="a2",
            analysis="h2",
        ),
        document_row("i7", uid(7), "info", revision=2),
        document_row("a7", uid(7), "analysis_ai", status="ready_for_review", info="i7-old"),
    ]

    def manual(card_id: str, loop_id: str, number: int) -> CardsRow:
        return card_row(card_id, f"doing-{loop_id}", loop_id).__replace__(
            kind="manual", ticket_key=f"L-{number}-UNP-001"
        )

    state.cards = {
        "solo": manual("solo", uid(5), 5).__replace__(completed_at=CREATED),
        "open": manual("open", uid(8), 8),
        "asks": manual("asks", uid(9), 9).__replace__(waiting_for="decision"),
    }
    planned = "plan-1"
    loops = [
        loop(uid(1), "analysis_review", 1),
        loop(uid(2), "roadmap_review", 2),
        loop(uid(3), "awaiting_qa", 3).__replace__(current_plan_id=planned),
        loop(uid(4), "in_progress", 4).__replace__(current_plan_id=planned),
        loop(uid(5), "in_progress", 5),
        loop(uid(6), "draft", 6),
        loop(uid(7), "analysis_review", 7),
        loop(uid(8), "in_progress", 8).__replace__(current_plan_id=planned),
        loop(uid(9), "in_progress", 9).__replace__(current_plan_id=planned),
    ]
    return loop_world(
        settings,
        loops,
        items=[done(readiness_item("planned"))],
        state=state,
        public_url=public_url,
    )


def links(answer: ToolResult) -> dict[object, object]:
    return {row["key"]: row["decision_link"] for row in rows(answer)}


def decision_paths() -> dict[object, object]:
    """Each Loop's ``decision_link`` without a public address: the path inside Tralala."""
    loop_page = f"/boards/{BOARD_ID}/loops/"
    return {
        "L-1": f"{loop_page}{uid(1)}?tab=plan&doc=analysis",
        "L-2": f"{loop_page}{uid(2)}?tab=plan&doc=roadmap",
        "L-3": f"{loop_page}{uid(3)}?dialog=completion",
        "L-4": f"{loop_page}{uid(4)}?dialog=completion",
        "L-5": f"{loop_page}{uid(5)}?dialog=completion",
        "L-6": None,
        "L-7": None,
        "L-8": None,
        "L-9": None,
    }


def test_a_row_links_the_decision_a_person_takes_next_and_nothing_else(settings: Settings) -> None:
    answer = loop_summaries(decisions_world(settings), READER, ask())
    assert links(answer) == decision_paths()
    by_key = {row["key"]: row for row in rows(answer)}
    # A link only where the row waits on a person, and not for every such row: Info to write
    # and a Ticket's answer are not one decision of the Loop.
    for key, link in decision_paths().items():
        row = by_key[key]
        assert link is None or row["waiting_on"] == "person", key
    assert [by_key[key]["waiting_on"] for key in ("L-6", "L-7", "L-8", "L-9")] == [
        "person",
        "agent",
        "anyone",
        "person",
    ]
    # Every Ticket done: the implementation is a person's to accept, in the completion dialog;
    # in a Loop without a plan that acceptance closes the Loop, and the sentence says so.
    assert (by_key["L-4"]["next"], by_key["L-5"]["next"]) == (ALL_DONE, ALL_DONE_WITHOUT_PLAN)
    assert (by_key["L-5"]["without_plan"], by_key["L-4"]["without_plan"]) == (True, False)


def test_a_loop_without_a_plan_links_the_one_decision_that_closes_it(settings: Settings) -> None:
    """The fast track: every Ticket of a Loop without a plan is done, and accepting the
    implementation closes it with no QA. The address is the completion dialog, as for a planned
    Loop; while a Ticket is still open nothing waits for a person."""
    solo = uid(5)
    state = BoardState()
    state.cards = {
        "u": card_row("u", f"todo-{solo}", solo).__replace__(
            kind="manual", ticket_key="L-1-UNP-001"
        ),
        "v": card_row("v", f"doing-{solo}", solo).__replace__(
            kind="manual", ticket_key="L-1-UNP-002", completed_at=CREATED
        ),
    }
    world = loop_world(settings, [loop(solo, "in_progress", 1)], state=state)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["without_plan"], row["waiting_on"], row["decision_link"]) == (True, "anyone", None)
    state.cards["u"] = state.cards["u"].__replace__(completed_at=CREATED)
    (row,) = rows(loop_summaries(world, READER, ask()))
    assert (row["without_plan"], row["next"], row["waiting_on"]) == (
        True,
        ALL_DONE_WITHOUT_PLAN,
        "person",
    )
    assert row["decision_link"] == f"/boards/{BOARD_ID}/loops/{solo}?dialog=completion"


def test_with_a_public_url_every_link_is_absolute(settings: Settings) -> None:
    answer = loop_summaries(decisions_world(settings, public_url=PUBLIC), READER, ask())
    assert links(answer) == {
        key: None if path is None else f"{PUBLIC}{path}" for key, path in decision_paths().items()
    }


ASK_FOR_ROADMAP = (
    "Ask for the RoadMap (run_roadmap) or hand one in, written to a board agent's instructions "
    "(read_instructions, then write_roadmap)."
)


def planning_world(settings: Settings, *, public_url: str | None = None) -> LoopWorld:
    """Five Loops in ``planning``, each with an approved analysis: a Loop stays in that stage once
    a RoadMap is handed in (``compute_stage``).

    L-1 has no RoadMap, L-2 one ready for review, L-3 one a person asked to change, L-4 one out of
    date with its Info, and L-5 the empty draft a reset of the RoadMap leaves.
    """
    state = BoardState()

    def roadmap(
        n: int, status: str, *, content: str = "text", info: str = ""
    ) -> list[LoopDocumentsRow]:
        loop_id = uid(n)
        return [
            document_row(
                f"r{n}",
                loop_id,
                "roadmap_ai",
                status=status,
                content=content,
                info=info or f"i{n}",
                analysis_ai=f"a{n}",
                analysis=f"h{n}",
            ),
            document_row(
                f"m{n}", loop_id, "roadmap", status=status, content=content, roadmap_ai=f"r{n}"
            ),
        ]

    for n in range(1, 6):
        state.documents += [
            document_row(f"i{n}", uid(n), "info"),
            document_row(f"a{n}", uid(n), "analysis_ai", status="approved", info=f"i{n}"),
            document_row(f"h{n}", uid(n), "analysis", status="approved", analysis_ai=f"a{n}"),
        ]
    state.documents += [
        *roadmap(2, "ready_for_review"),
        *roadmap(3, "changes_requested"),
        *roadmap(4, "ready_for_review", info="i4-old"),
        *roadmap(5, "draft", content=""),
    ]
    loops = [loop(uid(n), "planning", n) for n in range(1, 6)]
    return loop_world(settings, loops, state=state, public_url=public_url)


def test_a_roadmap_handed_in_while_the_loop_is_planning_waits_for_a_person_and_links_it(
    settings: Settings,
) -> None:
    answer = loop_summaries(planning_world(settings), READER, ask())
    by_key = {row["key"]: row for row in rows(answer)}
    review = f"/boards/{BOARD_ID}/loops/{uid(2)}?tab=plan&doc=roadmap"
    reviews = "A person reviews the RoadMap and approves it or asks for changes."
    assert {
        key: (row["next"], row["waiting_on"], row["decision_link"]) for key, row in by_key.items()
    } == {
        # Nothing handed in yet: the RoadMap is asked for, as before.
        "L-1": (ASK_FOR_ROADMAP, "agent", None),
        # Handed in: a person reviews it in the Plan tab.
        "L-2": (reviews, "person", review),
        # Sent back, or out of date with its inputs: an agent hands in a new one, no link.
        "L-3": ("A person asked for changes to the RoadMap: hand in a new one.", "agent", None),
        "L-4": ("The RoadMap is out of date with its inputs: hand in a new one.", "agent", None),
        # A reset left an empty draft: nothing to review, the RoadMap is asked for again.
        "L-5": (ASK_FOR_ROADMAP, "agent", None),
    }
    assert {key: row["stage"] for key, row in by_key.items()} == dict.fromkeys(by_key, "planning")
    documents = by_key["L-2"]["documents"]
    assert isinstance(documents, Mapping)
    assert (documents["roadmap_ai"], documents["roadmap"]) == ("ready_for_review r1",) * 2
    # With the installation's public address the same link is absolute; the others stay null.
    public = loop_summaries(planning_world(settings, public_url=PUBLIC), READER, ask())
    assert links(public) == {
        "L-1": None,
        "L-2": f"{PUBLIC}{review}",
        "L-3": None,
        "L-4": None,
        "L-5": None,
    }


def test_an_empty_analysis_draft_left_by_a_reset_is_asked_for_and_waits_for_no_review(
    settings: Settings,
) -> None:
    """A reset of the analysis leaves an empty draft as the current revision, which keeps the Loop
    in ``analysis_review`` (``compute_stage``): L-1 has an analysis to review, L-2 only the draft.
    """
    state = BoardState()
    state.documents = [
        document_row("i1", uid(1), "info"),
        document_row("a1", uid(1), "analysis_ai", status="ready_for_review", info="i1"),
        document_row("h1", uid(1), "analysis", status="ready_for_review", analysis_ai="a1"),
        document_row("i2", uid(2), "info"),
        document_row("a2", uid(2), "analysis_ai", content="", info="i2"),
        document_row("h2", uid(2), "analysis", content="", analysis_ai="a2"),
    ]
    loops = [loop(uid(1), "analysis_review", 1), loop(uid(2), "analysis_review", 2)]
    answer = loop_summaries(loop_world(settings, loops, state=state), READER, ask())
    by_key = {row["key"]: row for row in rows(answer)}
    assert {
        key: (row["next"], row["waiting_on"], row["decision_link"]) for key, row in by_key.items()
    } == {
        "L-1": (
            "A person reviews the analysis and approves it or asks for changes.",
            "person",
            f"/boards/{BOARD_ID}/loops/{uid(1)}?tab=plan&doc=analysis",
        ),
        "L-2": (
            "The analysis has no text: ask for one (run_analysis) or hand one in, written to a "
            "board agent's instructions (read_instructions, then write_analysis).",
            "agent",
            None,
        ),
    }


# --- the Tickets the key has not reported on -----------------------------------------------------

THEN = (
    "list_tickets with a loop_id (or key) lists its Tickets, narrowed by column, assignee me, "
    "state or needs_person; read_loop gives one Loop's documents, Phases and notes."
)


def taken_world(settings: Settings) -> LoopWorld:
    """Loop L-1 in progress, with its planned Ticket ``c1`` (L-1-DE01-001) in Doing, which the key
    moved at ``MOVED`` and has not reported on since."""
    state = BoardState()
    state.cards = {
        "c1": card_row("c1", "doing-run", "run", plan_item_id="item-c1").__replace__(
            ticket_key="L-1-DE01-001", title="Read the log"
        ),
    }
    state.activity.append(
        activity_row("e-1", "card.moved", "c1", actor_id=KEY.actor_id, timestamp=MOVED)
    )
    run = loop("run", "in_progress", 1).__replace__(current_plan_id="plan-1")
    return loop_world(settings, [run], items=[readiness_item("c1")], state=state)


def test_loop_summaries_names_the_tickets_the_key_took_and_has_not_reported_on(
    settings: Settings,
) -> None:
    world = taken_world(settings)
    answer = loop_summaries(world, KEY, ask())
    assert answer == {
        "board_id": BOARD_ID,
        "loops": [
            {
                "id": "run",
                "key": "L-1",
                "name": "Loop run",
                "goal": "",
                "stage": "in_progress",
                "without_plan": False,
                "next": "1 Ticket is ready to start.",
                "waiting_on": "anyone",
                "decision_link": None,
                "execution_allowed": True,
                "tickets": {
                    "ready": 1,
                    "needs_input": 0,
                    "blocked": 0,
                    "not_done": 0,
                    "completed": 0,
                    "total": 1,
                    "needs_person": 0,
                    "awaiting_confirmation": 0,
                    "by_column": {"Todo": 0, "Doing": 1},
                },
                "documents": {
                    "info": "empty",
                    "analysis_ai": "empty",
                    "analysis": "empty",
                    "roadmap_ai": "empty",
                    "roadmap": "empty",
                },
                "poc_decisions": {
                    "open": 0,
                    "built_on_open": 0,
                    "missing_open": 0,
                    "due": 0,
                    "answered": 0,
                },
            }
        ],
        "count": 1,
        "unreported": [
            {
                "id": "c1",
                "key": "L-1-DE01-001",
                "title": "Read the log",
                "loop": "L-1",
                "taken_at": MOVED,
            }
        ],
        "next_step": (
            "Report on each Ticket under unreported with comment_ticket, set_ticket_wait or "
            "complete_ticket before you move another Ticket. " + THEN
        ),
    }
    assert answer["next_step"] == f"{REPORT_FIRST} {THEN}"
    # The key's standing on the board, whatever the stage asked for.
    planning = loop_summaries(world, KEY, ask(stage="planning"))
    assert (planning["count"], planning["unreported"]) == (0, answer["unreported"])


def test_loop_summaries_names_nothing_for_a_person_or_a_role_agent_or_after_a_report(
    settings: Settings,
) -> None:
    world = taken_world(settings)
    # The same actor id as the key that moved c1: only an issued key owes a report.
    person = KEY.__replace__(actor_type="user", credential_id=None)
    role_agent = KEY.__replace__(credential_id=None)
    for actor in (person, role_agent):
        answer = loop_summaries(world, actor, ask())
        assert (answer["unreported"], answer["next_step"]) == ([], THEN)
    world.state.comments["m-1"] = comment_row("m-1", "c1", actor_id=KEY.actor_id, created_at=LATER)
    answer = loop_summaries(world, KEY, ask())
    assert (answer["unreported"], answer["next_step"]) == ([], THEN)


def test_loop_summaries_is_offered_to_loops_read_and_documented(settings: Settings) -> None:
    assert tool_catalog()["loop_summaries"].scopes == ("loops:read",)
    assert "loop_summaries" in {tool["name"] for tool in tool_list(READER)}
    assert "### loop_summaries (requires `loops:read`)" in render_bootstrap(settings)


# --- the POC decisions a Loop holds --------------------------------------------------------------


def test_each_loop_row_counts_its_poc_decisions_read_for_the_whole_board(
    settings: Settings,
) -> None:
    """Every planned Ticket is done, so every open record is due; a Loop without records counts
    none, and the counts come from one read for the board."""
    writer = ActorContext(
        actor_id="user-ada",
        actor_type="user",
        actor_name="Ada",
        scopes=frozenset({"cards:read", "cards:write", "loops:read"}),
    )
    loops = [loop(uid(1), "in_progress", 1), loop(uid(2), "in_progress", 2)]
    world = loop_world(settings, loops, items=[done(readiness_item("c1"))])
    common = {"reason": "It is quick.", "change_path": "Change it later."}
    built = PocDecisionCreate.model_validate(
        {
            "kind": "decision",
            "title": "Keep the list local",
            "chosen": "In the browser.",
            "alternative": "On the server.",
            "builds_on": "The export reads it.",
            **common,
        }
    )
    gone = PocDecisionCreate.model_validate(
        {
            "kind": "missing",
            "title": "No mail account",
            "missing": "An account.",
            "chosen": "Show a link.",
            **common,
        }
    )
    answered = PocDecisionCreate.model_validate(
        {
            "kind": "decision",
            "title": "Name the column",
            "chosen": "Todo.",
            "alternative": "Backlog.",
            **common,
        }
    )
    for payload in (built, gone, answered):
        world.poc_decisions.record(writer, BOARD_ID, uid(1), payload)
    last = world.state.poc_decisions[-1].id
    world.poc_decisions.answer(
        writer, BOARD_ID, uid(1), last, PocDecisionAnswerCreate(answer="ok")
    )
    summaries = rows(loop_summaries(world, READER, ask()))
    by_key = {row["key"]: row["poc_decisions"] for row in summaries}
    assert by_key == {
        "L-1": {"open": 2, "built_on_open": 1, "missing_open": 1, "due": 2, "answered": 1},
        "L-2": {"open": 0, "built_on_open": 0, "missing_open": 0, "due": 0, "answered": 0},
    }
