"""Where a Ticket's work is done and what it waits for, on the fakes: the computed state for every
combination of blockers and wait, the revision's defaults read back through the generated row, the
writes and their refusals (``TicketWorkService``), completion with an open wait, the RoadMap's
starting values and labels, and the worker tools that read and set them (``set_ticket_wait``,
``create_ticket``, ``complete_ticket`` and ``allowed_actions``)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeIs

import pytest
from pydantic import JsonValue, ValidationError

from app.api.mcp import render_bootstrap, tool_list
from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, ValidationFailure, VersionConflict
from app.db.generated.board import CARDS_COLUMNS, CardsRow, LabelsRow
from app.repositories.cards import CardCounts
from app.schemas.cards import CardCreate, TicketWaitClear, TicketWaitSet, TicketWorkplaceUpdate
from app.schemas.loops import HumanConfirmation, PlanPayload
from app.services.agent_tools import (
    ToolResult,
    allowed_actions,
    complete_ticket,
    create_ticket,
    set_ticket_wait,
    tool_catalog,
)
from app.services.cards import CardService, card_entry
from app.services.lists import ListService
from app.services.loop_generation_prompts import (
    PURPOSE_PROMPTS,
    TICKET_WORK_RULES,
    context_labels,
    parse_output,
)
from app.services.loop_plans import LoopPlanService
from app.services.loops import LoopService
from app.services.subresources import CommentService
from app.services.ticket_state import needs_person, ticket_state
from app.services.ticket_work import TicketWorkService
from tests.unit.faces import FACE
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
)
from tests.unit.fakes.plans import FakePlanViews, plan_views, readiness_item
from tests.unit.fakes.registry import FakeRegistryUnitOfWork, RegistryState

NOW = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
STAMP = "2026-11-07T09:00:00Z"
LOOP = "loop-a"
REVISION = Path(__file__).resolve().parents[2] / "migrations/board/versions/0017_ticket_work.py"
WORKER = ActorContext(
    actor_id="agent-1",
    actor_type="agent",
    actor_name="Worker",
    scopes=frozenset({"cards:read", "cards:write", "comments:write", "loops:read"}),
)
READER = WORKER.__replace__(scopes=frozenset({"cards:read", "loops:read"}))
PERSON = ActorContext(
    actor_id="person-1",
    actor_type="user",
    actor_name="Grace",
    scopes=frozenset({"cards:read", "cards:write", "comments:write", "loops:read"}),
)
WAITS = ("nothing", "decision", "information", "access", "third_party")


# --- the state -----------------------------------------------------------------------------------


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("waiting_for", WAITS)
def test_the_state_of_every_wait_with_and_without_blockers(waiting_for: str, blocked: bool) -> None:
    # needs_input beats blocked: a person can answer now even when earlier work is unfinished.
    expected = (
        "needs_input"
        if waiting_for in ("decision", "information", "access")
        else "blocked"
        if blocked or waiting_for == "third_party"
        else "ready"
    )
    assert ticket_state(completed=False, waiting_for=waiting_for, blocked=blocked) == expected
    # A completed Ticket has no state.
    assert ticket_state(completed=True, waiting_for=waiting_for, blocked=blocked) is None


def test_what_needs_a_person_is_an_answer_or_a_persons_task_that_may_start() -> None:
    assert needs_person("needs_input", human_action_required=False)
    assert needs_person("needs_input", human_action_required=True)
    assert needs_person("ready", human_action_required=True)
    assert not needs_person("ready", human_action_required=False)
    assert not needs_person("blocked", human_action_required=True)
    assert not needs_person(None, human_action_required=True)


def test_a_ticket_from_before_the_revision_reads_unknown_and_waits_for_nothing() -> None:
    """The revision's defaults, as SQLite gives them to every row already there, read back through
    the generated row: nothing old claims where its work is done or what it waits for."""
    text = REVISION.read_text(encoding="utf-8")
    defaults = dict(re.findall(r"(\w+) TEXT \{_(\w+)\}", text))
    assert set(defaults) >= {"workplace", "waiting_for", "waiting_reason"}
    assert "NOT NULL DEFAULT 'unknown'" in text and "NOT NULL DEFAULT 'nothing'" in text
    assert 'ALTER TABLE cards ADD COLUMN waiting_set_by TEXT"' in text
    new = {"workplace": "unknown", "waiting_for": "nothing", "waiting_reason": ""}
    old = {
        key: value
        for key, value in asdict(card_row("c", "todo", LOOP)).items()
        if not key.startswith(("workplace", "waiting"))
    }
    mapping: dict[str, object] = {
        **old,
        **new,
        "waiting_set_at": None,
        "waiting_set_by": None,
    }
    assert set(mapping) == set(CARDS_COLUMNS)
    row = CardsRow.from_mapping(mapping)
    counts = CardCounts(checklist_total=0, checklist_completed=0, comment_count=0)
    entry = card_entry(BOARD_ID, row, [], counts, None)
    assert (entry["workplace"], entry["waiting_for"], entry["waiting_reason"]) == (
        "unknown",
        "nothing",
        "",
    )
    assert (entry["state"], entry["needs_person"]) == ("ready", False)


def test_a_ticket_entry_carries_its_state_from_its_wait_and_its_plan() -> None:
    blocked = readiness_item("c", ready=False)
    row = card_row("c", "todo", LOOP)
    counts = CardCounts(checklist_total=0, checklist_completed=0, comment_count=0)
    assert card_entry(BOARD_ID, row, [], counts, blocked)["state"] == "blocked"
    asked = row.__replace__(waiting_for="decision", waiting_reason="Which one?")
    assert card_entry(BOARD_ID, asked, [], counts, blocked)["state"] == "needs_input"
    assert card_entry(BOARD_ID, asked, [], counts, blocked)["needs_person"] is True
    assert (
        card_entry(BOARD_ID, row.__replace__(completed_at=STAMP), [], counts, None)["state"] is None
    )


# --- the writes ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class World:
    """What the tools declare they use of the composition root, and the board."""

    card: CardService
    comment: CommentService
    loop: LoopService
    list: ListService
    ticket_work: TicketWorkService
    state: BoardState


def world(settings: Settings) -> World:
    """An executing Loop with a planned Ticket ``t`` (ready), a manual one ``m`` and a human-only
    one ``h``, in Todo; the board has the labels Development and UX."""
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="ready").__replace__(current_plan_id="plan-1")}
    state.lists = {"todo": list_row("todo", LOOP, 512, name="Todo")}
    state.labels = {
        "dev": LabelsRow(id="dev", name="Development", color="#000000"),
        "ux": LabelsRow(id="ux", name="UX", color="#ffffff"),
    }
    state.cards = {
        "t": card_row("t", "todo", LOOP, plan_item_id="item-t").__replace__(
            ticket_key="K-1", kind="ticket"
        ),
        "m": card_row("m", "todo", LOOP).__replace__(ticket_key="L-1-UNP-001", kind="manual"),
        "h": card_row("h", "todo", LOOP).__replace__(ticket_key="K-2", required_actor="human"),
    }
    views = plan_views(FakePlanViews(items=[readiness_item("t")]))
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(state)
    accounts = FakeRegistryUnitOfWork(RegistryState())
    cards = CardService(settings, checks, store, accounts, plans=views, clock=lambda: NOW)
    return World(
        card=cards,
        comment=CommentService(checks, store, accounts),
        loop=LoopService(settings, checks, store, plans=views, tickets=cards, clock=lambda: NOW),
        list=ListService(checks, store),
        ticket_work=TicketWorkService(checks, store, cards, clock=lambda: NOW),
        state=state,
    )


def wait(
    waiting_for: str = "decision", reason: str = "Which provider?", version: int = 1
) -> TicketWaitSet:
    return TicketWaitSet.model_validate(
        {"version": version, "waiting_for": waiting_for, "reason": reason}
    )


def test_a_token_sets_a_wait_with_its_reason_and_the_ticket_needs_input(
    settings: Settings,
) -> None:
    w = world(settings)
    entry = w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait())
    assert (entry["waiting_for"], entry["waiting_reason"], entry["version"]) == (
        "decision",
        "Which provider?",
        2,
    )
    assert (entry["waiting_set_by"], entry["waiting_set_at"]) == ("agent-1", STAMP)
    assert (entry["state"], entry["needs_person"]) == ("needs_input", True)
    logged = [row.action for row in w.state.activity]
    assert logged[-1] == "card.wait_set"
    # The same wait again changes nothing and keeps the version.
    again = w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait(version=2))
    assert again["version"] == 2
    # A third party blocks it; it does not need input.
    third = w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "m", wait("third_party", "The key"))
    assert (third["state"], third["needs_person"]) == ("blocked", False)


def test_clearing_or_replacing_a_wait_is_a_persons_act(settings: Settings) -> None:
    w = world(settings)
    w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait("third_party", "The supplier"))
    for refused in (
        lambda: w.ticket_work.clear_wait(WORKER, BOARD_ID, LOOP, "t", TicketWaitClear(version=2)),
        lambda: w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait(version=2)),
    ):
        with pytest.raises(Forbidden) as caught:
            refused()
        assert caught.value.code == "human_action_required"
    assert w.state.cards["t"].waiting_for == "third_party"
    replaced = w.ticket_work.set_wait(PERSON, BOARD_ID, LOOP, "t", wait(version=2))
    assert (replaced["waiting_for"], replaced["waiting_set_by"]) == ("decision", "person-1")
    cleared = w.ticket_work.clear_wait(PERSON, BOARD_ID, LOOP, "t", TicketWaitClear(version=3))
    assert (cleared["waiting_for"], cleared["waiting_reason"], cleared["waiting_set_by"]) == (
        "nothing",
        "",
        None,
    )
    assert (cleared["state"], cleared["version"]) == ("ready", 4)
    assert w.state.activity[-1].action == "card.wait_cleared"


def test_the_workplace_describes_the_work_so_a_token_may_change_it(settings: Settings) -> None:
    w = world(settings)
    entry = w.ticket_work.set_workplace(
        WORKER, BOARD_ID, LOOP, "t", TicketWorkplaceUpdate(version=1, workplace="codebase")
    )
    assert (entry["workplace"], entry["version"]) == ("codebase", 2)
    with pytest.raises(ValidationError):
        TicketWorkplaceUpdate.model_validate({"version": 2, "workplace": "agent"})


def test_every_write_is_version_checked_and_refused_where_it_cannot_apply(
    settings: Settings,
) -> None:
    w = world(settings)
    with pytest.raises(VersionConflict):
        w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait(version=9))
    w.state.cards["m"] = w.state.cards["m"].__replace__(completed_at=STAMP)
    with pytest.raises(Conflict) as completed:
        w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "m", wait())
    assert completed.value.code == "ticket_completed"
    with pytest.raises(Forbidden):
        w.ticket_work.set_wait(READER, BOARD_ID, LOOP, "t", wait())
    w.state.loops["loop-b"] = loop_row("loop-b", stage="ready")
    with pytest.raises(Conflict) as mismatch:
        w.ticket_work.set_wait(WORKER, BOARD_ID, "loop-b", "t", wait())
    assert mismatch.value.code == "loop_mismatch"
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(stage="completed", completed_at=STAMP)
    with pytest.raises(Conflict) as read_only:
        w.ticket_work.set_workplace(
            WORKER, BOARD_ID, LOOP, "t", TicketWorkplaceUpdate(version=1, workplace="outside")
        )
    assert read_only.value.code == "loop_read_only"
    for malformed in (
        {"version": 1, "waiting_for": "nothing", "reason": "x"},
        {"version": 1, "waiting_for": "decision", "reason": " "},
        {"version": 1, "waiting_for": "decision", "reason": "x" * 501},
    ):
        with pytest.raises(ValidationError):
            TicketWaitSet.model_validate(malformed)


def test_a_ticket_with_an_open_wait_is_not_completed_until_a_person_clears_it(
    settings: Settings,
) -> None:
    w = world(settings)
    w.state.cards["t"] = w.state.cards["t"].__replace__(
        waiting_for="information", waiting_reason="The address"
    )
    w.state.cards["h"] = w.state.cards["h"].__replace__(
        waiting_for="access", waiting_reason="The admin login"
    )
    answer = None
    with pytest.raises(Conflict) as refused:
        answer = complete_ticket(
            w, WORKER, {"board_id": BOARD_ID, "card_id": "t", "summary": "Done."}
        )
    assert answer is None
    assert refused.value.code == "ticket_waiting"
    assert refused.value.details is not None
    assert refused.value.details["wait"] == {
        "waiting_for": "information",
        "reason": "The address",
        "set_by": None,
        "set_at": None,
    }
    assert "comment_id" in refused.value.details  # the summary is kept as a comment
    with pytest.raises(Conflict) as confirmation:
        w.loop.confirm_human_ticket(
            PERSON, BOARD_ID, LOOP, "h", HumanConfirmation(version=1, note="Done")
        )
    assert confirmation.value.code == "ticket_waiting"
    w.ticket_work.clear_wait(PERSON, BOARD_ID, LOOP, "t", TicketWaitClear(version=1))
    done = complete_ticket(w, WORKER, {"board_id": BOARD_ID, "card_id": "t", "summary": "Done."})
    assert w.state.cards["t"].completed_at == STAMP
    assert "ticket" in done


# --- a planned Ticket's starting values ----------------------------------------------------------


def uid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def roadmap(**ticket: JsonValue) -> PlanPayload:
    return PlanPayload.model_validate(
        {
            "phases": [
                {
                    "id": uid(1),
                    "number": 1,
                    "name": "Build",
                    "tickets": [{**FACE, "id": uid(11), "title": "Add the login", **ticket}],
                }
            ]
        }
    )


def test_the_roadmap_describes_where_the_work_is_done_and_what_it_waits_for() -> None:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP, stage="planning")}
    state.lists = {"todo": list_row("todo", LOOP, 512)}
    state.labels = {"dev": LabelsRow(id="dev", name="Development", color="#000000")}
    plans = LoopPlanService(clock=lambda: NOW)
    repos = FakeBoardRepositories(state)
    plan = roadmap(
        workplace="codebase",
        waiting_for="decision",
        waiting_reason="Which provider?",
        labels=["development"],
    )
    draft = plans.register_draft(repos, state.loops[LOOP], plan, PERSON)
    item = state.plan_items[uid(11)]
    assert (item.workplace, item.waiting_for, item.waiting_reason) == (
        "codebase",
        "decision",
        "Which provider?",
    )
    plans.publish(repos, state.loops[LOOP], draft["plan_id"], PERSON, approval_id=None)
    card = state.cards[uid(11)]
    assert (card.workplace, card.waiting_for, card.waiting_reason) == (
        "codebase",
        "decision",
        "Which provider?",
    )
    assert (card.waiting_set_by, card.waiting_set_at) == ("person-1", STAMP)
    assert [link.label_id for link in state.card_labels if link.card_id == uid(11)] == ["dev"]
    # A label the board does not have is refused with the names there are...
    with pytest.raises(ValidationFailure) as unknown:
        plans.register_draft(repos, state.loops[LOOP], roadmap(labels=["Marketing"]), PERSON)
    assert unknown.value.details == {"unknown": ["Marketing"], "labels": ["Development"]}
    # ...unless a generated RoadMap's model named it: it is then left out.
    plans.register_draft(
        repos, state.loops[LOOP], roadmap(labels=["Marketing"]), PERSON, drop_unknown_labels=True
    )
    # A wait says why; a planned Ticket without one describes nothing it waits for.
    with pytest.raises(ValidationError):
        roadmap(waiting_for="access")
    assert roadmap().phases[0].tickets[0].workplace == "unknown"


def test_the_roadmap_agent_describes_the_work_and_names_only_the_boards_labels() -> None:
    prompt = PURPOSE_PROMPTS["roadmap"]
    assert TICKET_WORK_RULES in prompt
    assert "never write that an agent does one" in TICKET_WORK_RULES
    assert all(word in TICKET_WORK_RULES for word in ("workplace", "waiting_reason", "labels"))
    answer = json.dumps(roadmap(labels=["Development"]).model_dump())
    assert parse_output("roadmap", answer, labels=("development", "UX"))["phases"]
    # An unknown label goes back to the model with the names there are, for a repair.
    with pytest.raises(ValidationFailure, match=r"Use only the names in context.labels: UX"):
        parse_output("roadmap", answer, labels=("UX",))
    # A run captured before the context carried labels is not checked here.
    assert parse_output("roadmap", answer)["phases"]
    assert context_labels({"context": {"labels": ["UX", 3]}}) == ("UX",)
    assert context_labels({"context": {}}) is None


# --- the worker tools ----------------------------------------------------------------------------


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def part(answer: ToolResult, key: str) -> Mapping[str, object]:
    value = answer[key]
    assert _is_mapping(value)
    return value


def test_set_ticket_wait_sets_a_wait_with_its_reason_and_says_who_clears_it(
    settings: Settings,
) -> None:
    w = world(settings)
    answer = set_ticket_wait(
        w,
        WORKER,
        {"board_id": BOARD_ID, "card_id": "t", "waiting_for": "access", "reason": "The API key"},
    )
    ticket = part(answer, "ticket")
    assert (ticket["state"], ticket["version"]) == ("needs_input", 2)
    assert answer["wait"] == {
        "waiting_for": "access",
        "reason": "The API key",
        "set_by": "agent-1",
        "set_at": STAMP,
    }
    assert "person" in str(answer["next_step"])
    for arguments, argument in (
        ({"waiting_for": "nothing", "reason": "x"}, "waiting_for"),
        ({"waiting_for": "lunch", "reason": "x"}, "waiting_for"),
        ({"waiting_for": "decision"}, "reason"),
    ):
        with pytest.raises(ValidationFailure) as refused:
            set_ticket_wait(w, WORKER, {"board_id": BOARD_ID, "card_id": "m", **arguments})
        assert argument in refused.value.message or (
            refused.value.details is not None and refused.value.details.get("argument") == argument
        )
    with pytest.raises(Forbidden):
        set_ticket_wait(
            w,
            READER,
            {"board_id": BOARD_ID, "card_id": "m", "waiting_for": "decision", "reason": "x"},
        )


def test_create_ticket_says_where_the_work_is_done_what_it_waits_for_and_its_area(
    settings: Settings,
) -> None:
    w = world(settings)
    answer = create_ticket(
        w,
        WORKER,
        {
            "board_id": BOARD_ID,
            "loop_id": LOOP,
            "title": "Rotate the key",
            "workplace": "outside",
            "waiting_for": "access",
            "waiting_reason": "The admin console",
            "labels": ["ux", "Development"],
        },
    )
    ticket = part(answer, "ticket")
    assert (ticket["state"], ticket["workplace"], ticket["labels"]) == (
        "needs_input",
        "outside",
        ["Development", "UX"],
    )
    card = w.state.cards[str(ticket["id"])]
    assert (card.waiting_for, card.waiting_set_by) == ("access", "agent-1")
    with pytest.raises(ValidationFailure) as unknown:
        create_ticket(
            w,
            WORKER,
            {"board_id": BOARD_ID, "loop_id": LOOP, "title": "New", "labels": ["Legal"]},
        )
    assert unknown.value.details == {"unknown": ["Legal"], "labels": ["Development", "UX"]}
    assert len(w.state.labels) == 2  # never created
    with pytest.raises(ValidationFailure, match="waiting_reason"):
        create_ticket(
            w,
            WORKER,
            {"board_id": BOARD_ID, "loop_id": LOOP, "title": "New", "waiting_for": "decision"},
        )
    # The REST create keeps creating a label it does not know, as it always did.
    created = CardCreate(list_id="todo", title="Via REST", labels=["Ops"])
    assert created.workplace == "unknown"


def test_a_worker_is_offered_set_ticket_wait_until_a_wait_is_set(settings: Settings) -> None:
    w = world(settings)
    ready = allowed_actions(w.card.get(BOARD_ID, LOOP, "t"), execution_allowed=True)
    assert ready[-2:] == ["set_ticket_wait", "complete_ticket"]
    w.ticket_work.set_wait(WORKER, BOARD_ID, LOOP, "t", wait())
    # Waiting for an answer: neither another wait nor a completion.
    waiting = allowed_actions(w.card.get(BOARD_ID, LOOP, "t"), execution_allowed=True)
    assert waiting == ready[:-2]
    person = allowed_actions(w.card.get(BOARD_ID, LOOP, "h"), execution_allowed=True)
    assert person[0] == "comment_ticket"
    assert person[-1] == "set_ticket_wait"
    assert "complete_ticket" not in person


def test_set_ticket_wait_is_offered_to_cards_write_and_no_tool_clears_a_wait(
    settings: Settings,
) -> None:
    catalogue = tool_catalog()
    assert catalogue["set_ticket_wait"].scopes == ("cards:write",)
    assert "set_ticket_wait" in {tool["name"] for tool in tool_list(WORKER)}
    assert "set_ticket_wait" not in {tool["name"] for tool in tool_list(READER)}
    assert not [name for name in catalogue if "clear" in name or "unblock" in name]
    text = render_bootstrap(settings)
    assert "### set_ticket_wait (requires `cards:write`)" in text
    listing = str(catalogue["list_tickets"].input_schema["properties"])
    assert all(word in listing for word in ("state", "workplace", "waiting_for", "needs_person"))
    assert "'ready'" not in listing
    created = str(catalogue["create_ticket"].input_schema)
    assert all(word in created for word in ("workplace", "waiting_reason", "labels"))
