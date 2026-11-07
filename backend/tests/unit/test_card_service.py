"""CardService's rules on an in-memory board: ownership, versions, plan scope, completion gates,
labels, assignees, ordering, the lists and the replayed keys.

The service runs its real code; the repositories, both units of work, the registry checks, the plan
views, the clock and the id source are the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure, VersionConflict
from app.db.generated.board import (
    CardLabelsRow,
    CardsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
    LabelsRow,
    LoopsRow,
)
from app.schemas.cards import BulkCardCreate, CardCreate, CardMove, CardUpdate
from app.services.cards import NEW_LABEL_COLOR, CardService, card_sort
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
    plan_row,
    qa_cycle_row,
)
from tests.unit.fakes.plans import BLOCKER, FakePlanViews, plan_views, readiness_item
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    agent_row,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
OTHER = "loop-b"
SCOPES = frozenset({"cards:read", "cards:write"})
HUMAN = ActorContext(
    actor_id="actor-1", actor_type="user", actor_name="Ada", scopes=SCOPES, request_id="req-1"
)
AGENT = ActorContext(actor_id="agent-1", actor_type="agent", actor_name="Bot", scopes=SCOPES)
READER = ActorContext(
    actor_id="actor-2", actor_type="user", actor_name="Reader", scopes=frozenset({"cards:read"})
)


class Ids:
    """new-1, new-2, ... in call order; ``clash`` hands out an id that is already taken once."""

    def __init__(self) -> None:
        self.issued = 0
        self.clash: dict[int, str] = {}

    def __call__(self) -> str:
        self.issued += 1
        return self.clash.pop(self.issued, f"new-{self.issued}")


@dataclass(slots=True)
class World:
    state: BoardState
    store: FakeBoardUnitOfWork
    checks: FakeBoardChecks
    views: FakePlanViews
    registry: RegistryState
    ids: Ids
    service: CardService

    def card(self, card_id: str) -> CardsRow:
        return self.state.cards[card_id]

    def actions(self) -> list[tuple[str, str]]:
        return [(entry.action, entry.entity_id) for entry in self.state.activity]


def world(settings: Settings, loop: LoopsRow | None = None) -> World:
    """Loop ``LOOP`` with lists todo (1024), doing (2048) and an archived one; Loop ``OTHER``
    with list elsewhere; labels Bug and Idea; a person, an agent and a disabled agent."""
    state = BoardState()
    state.loops = {
        LOOP: loop or loop_row(LOOP, stage="draft"),
        OTHER: loop_row(OTHER).__replace__(sequence=2, key="L-2"),
    }
    state.lists = {
        "todo": list_row("todo", LOOP, 1024, name="Todo"),
        "doing": list_row("doing", LOOP, 2048, name="Doing"),
        "shelf": list_row("shelf", LOOP, 3072, name="Shelf", archived_at=CREATED),
        "elsewhere": list_row("elsewhere", OTHER, 1024),
    }
    state.labels = {
        "bug": LabelsRow(id="bug", name="Bug", color="#ff0000"),
        "idea": LabelsRow(id="idea", name="Idea", color="#00ff00"),
    }
    registry = RegistryState()
    registry.actors = {
        "person": actor_row("person", name="Grace"),
        "gone": actor_row("gone", name="Gone", disabled_at=CREATED),
    }
    registry.agents = {
        "helper": agent_row("helper", name="Helper"),
        "asleep": agent_row("asleep", name="Asleep", enabled=False),
    }
    store = FakeBoardUnitOfWork(state)
    checks = FakeBoardChecks()
    views = FakePlanViews()
    ids = Ids()
    service = CardService(
        settings,
        checks,
        store,
        FakeRegistryUnitOfWork(registry),
        plans=plan_views(views),
        clock=lambda: NOW,
        new_id=ids,
    )
    return World(state, store, checks, views, registry, ids, service)


def put(w: World, card: CardsRow) -> CardsRow:
    w.state.cards[card.id] = card
    return card


# --- reads ----------------------------------------------------------------------------------------


def test_an_entry_is_the_row_its_labels_counts_and_readiness_in_the_former_key_order(
    settings: Settings,
) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP).__replace__(required_actor="human"))
    w.state.card_labels = [CardLabelsRow(card_id="c", label_id=label) for label in ("idea", "bug")]
    w.state.checklists = {"ch": ChecklistsRow(id="ch", card_id="c", title="Steps", position=1)}
    w.state.checklist_items = {
        "i1": ChecklistItemsRow(id="i1", checklist_id="ch", text="a", completed=1, position=1),
        "i2": ChecklistItemsRow(id="i2", checklist_id="ch", text="b", completed=0, position=2),
    }
    w.state.comments = {
        "m": CommentsRow(
            id="m", card_id="c", actor_id="a", content="x", created_at=CREATED, updated_at=CREATED
        )
    }
    entry = w.service.get(BOARD_ID, LOOP, "c")
    assert list(entry)[:2] == ["id", "list_id"]
    assert list(entry)[-19:] == [
        "workplace",
        "waiting_for",
        "waiting_reason",
        "waiting_set_at",
        "waiting_set_by",
        "board_id",
        "labels",
        "checklist_total",
        "checklist_completed",
        "comment_count",
        "human_action_required",
        "ready",
        "blockers",
        "downstream_phase_numbers",
        "acceptance_criteria",
        "expected_evidence",
        "phase_number",
        "state",
        "needs_person",
    ]
    assert entry["labels"] == [
        {"id": "bug", "name": "Bug", "color": "#ff0000"},
        {"id": "idea", "name": "Idea", "color": "#00ff00"},
    ]
    assert (entry["checklist_total"], entry["checklist_completed"], entry["comment_count"]) == (
        2,
        1,
        1,
    )
    assert entry["human_action_required"] is True
    assert (entry["ready"], entry["blockers"], entry["phase_number"]) == (True, [], None)
    assert w.views.calls == []


def test_a_planned_loop_decorates_each_card_from_its_planned_ticket(settings: Settings) -> None:
    w = world(settings, loop_row(LOOP, stage="ready").__replace__(current_plan_id="p"))
    put(w, card_row("t", "todo", LOOP).__replace__(required_actor="human"))
    put(w, card_row("m", "todo", LOOP).__replace__(required_actor="human", completed_at=STAMP))
    w.views.items = [readiness_item("t", ready=False, blockers=(BLOCKER,), phase_number=2)]
    w.views.items.append(readiness_item(None))
    manual, planned = w.service.list(BOARD_ID, LOOP)[0]
    assert (planned["ready"], planned["blockers"], planned["phase_number"]) == (False, [BLOCKER], 2)
    assert planned["human_action_required"] is False
    assert planned["acceptance_criteria"] == ["it works"]
    assert planned["downstream_phase_numbers"] == [2]
    assert (manual["ready"], manual["human_action_required"]) == (True, False)
    assert w.views.calls == [("readiness", LOOP, "ready")]


def test_reads_check_the_loop_the_card_and_its_owner(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    with pytest.raises(NotFound) as loop:
        w.service.get(BOARD_ID, "missing", "c")
    assert loop.value.code == "loop_not_found"
    with pytest.raises(NotFound, match="Card not found"):
        w.service.get(BOARD_ID, LOOP, "missing")
    with pytest.raises(Conflict) as mismatch:
        w.service.get(BOARD_ID, OTHER, "c")
    assert mismatch.value.code == "loop_mismatch"
    assert mismatch.value.details == {"loop_id": OTHER, "ticket_loop_id": LOOP}
    with pytest.raises(Conflict):
        w.service.require_membership(BOARD_ID, OTHER, "c")
    w.service.require_membership(BOARD_ID, LOOP, "c")
    w.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound, match="Board not found"):
        w.service.get(BOARD_ID, LOOP, "c")


def test_a_ticket_is_located_by_its_id_alone(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    loop_id, record = w.service.locate(BOARD_ID, "c")
    assert loop_id == LOOP
    assert record["version"] == 1
    assert "labels" not in record
    with pytest.raises(NotFound, match="Ticket not found"):
        w.service.locate(BOARD_ID, "missing")
    put(w, card_row("orphan", "todo", "gone"))
    with pytest.raises(NotFound, match="Ticket not found"):
        w.service.locate(BOARD_ID, "orphan")


def _cards(w: World) -> None:
    put(w, card_row("a", "todo", LOOP).__replace__(title="Write docs", priority="high"))
    put(
        w,
        card_row("b", "todo", LOOP).__replace__(
            title="Fix_100% bug",
            description="about DOCS",
            position=2048,
            due_at="2026-10-01T00:00:00Z",
            assignee_actor_id="person",
        ),
    )
    put(
        w,
        card_row("c", "doing", LOOP).__replace__(
            title="Third", due_at="2026-12-01T00:00:00Z", completed_at=STAMP, position=1024
        ),
    )
    put(w, card_row("d", "doing", LOOP, archived_at=CREATED).__replace__(title="Old"))
    put(w, card_row("x", "elsewhere", OTHER).__replace__(title="Write docs elsewhere"))
    w.state.card_labels = [CardLabelsRow(card_id="a", label_id="bug")]


def _ids(w: World, **filters: str | bool) -> list[str]:
    def text(name: str) -> str | None:
        value = filters.get(name)
        return value if isinstance(value, str) else None

    completed = filters.get("completed")
    entries, total = w.service.list(
        BOARD_ID,
        LOOP,
        list_id=text("list_id"),
        q=text("q"),
        label=text("label"),
        priority=text("priority"),
        due_before=text("due_before"),
        overdue=filters.get("overdue") is True,
        completed=completed if isinstance(completed, bool) else None,
        assignee=text("assignee"),
        include_archived=filters.get("include_archived") is True,
        sort=text("sort") or "position",
        order=text("order") or "asc",
    )
    assert total == len(entries)
    return [entry["id"] for entry in entries]


def test_the_list_filters_by_each_field_of_the_query(settings: Settings) -> None:
    w = world(settings)
    _cards(w)
    assert _ids(w) == ["a", "c", "b"]
    assert _ids(w, include_archived=True) == ["a", "c", "d", "b"]
    assert _ids(w, list_id="doing") == ["c"]
    assert _ids(w, q="docs") == ["a", "b"]
    assert _ids(w, q="100%") == ["b"]
    assert _ids(w, q="_") == ["a", "c", "b"]
    assert _ids(w, label="Bug") == ["a"]
    assert _ids(w, label="bug") == ["a"]
    assert _ids(w, priority="high") == ["a"]
    assert _ids(w, due_before="2026-10-15") == ["b"]
    assert _ids(w, overdue=True) == ["b"]
    assert _ids(w, completed=True) == ["c"]
    assert _ids(w, completed=False) == ["a", "b"]
    assert _ids(w, assignee="person") == ["b"]
    assert _ids(w, assignee="unassigned") == ["a", "c"]


def test_the_list_sorts_by_an_allowed_column_and_pages_after_counting(settings: Settings) -> None:
    w = world(settings)
    _cards(w)
    assert _ids(w, sort="title") == ["b", "c", "a"]
    assert _ids(w, sort="title", order="DESC") == ["a", "c", "b"]
    assert _ids(w, sort="due_at") == ["a", "b", "c"]
    assert _ids(w, sort="due_at", order="desc") == ["c", "b", "a"]
    assert _ids(w, sort="bogus") == ["a", "c", "b"]
    page, total = w.service.list(BOARD_ID, LOOP, limit=1, offset=1)
    assert ([entry["id"] for entry in page], total) == (["c"], 3)
    assert [card_sort(name) for name in ("title", "position", "x")] == [
        "title",
        "position",
        "position",
    ]


def test_a_due_filter_must_be_a_date_and_a_blank_one_matches_nothing(settings: Settings) -> None:
    w = world(settings)
    _cards(w)
    with pytest.raises(ValidationFailure):
        w.service.list(BOARD_ID, LOOP, due_before="soon")
    assert w.service.list(BOARD_ID, LOOP, due_before="  ") == ([], 0)
    with pytest.raises(NotFound):
        w.service.list(BOARD_ID, "missing", due_before="  ")


def test_the_board_list_shows_open_loops_cards_with_the_loop_that_owns_them(
    settings: Settings,
) -> None:
    w = world(settings)
    _cards(w)
    w.state.loops["done"] = loop_row("done", completed_at=STAMP).__replace__(sequence=3, key="D")
    w.state.loops["shelved"] = loop_row("shelved", archived_at=STAMP).__replace__(
        sequence=4, key="S"
    )
    put(w, card_row("in-done", "todo", "done"))
    put(w, card_row("in-shelved", "todo", "shelved"))
    w.state.cards["x"] = w.card("x").__replace__(ticket_key="KEY-9", position=1)
    tickets = w.service.list_board_tickets(BOARD_ID)
    assert [ticket["id"] for ticket in tickets] == ["a", "c", "b", "x"]
    assert list(tickets[0])[-8:] == [
        "loop_key",
        "loop_name",
        "loop_stage",
        "board_id",
        "labels",
        "checklist_total",
        "checklist_completed",
        "comment_count",
    ]
    assert (tickets[3]["loop_key"], tickets[3]["loop_name"]) == ("L-2", "Loop loop-b")
    assert [ticket["id"] for ticket in w.service.list_board_tickets(BOARD_ID, q="key-")] == ["x"]
    assert [ticket["id"] for ticket in w.service.list_board_tickets(BOARD_ID, limit=2)] == [
        "a",
        "c",
    ]


# --- create ---------------------------------------------------------------------------------------


def test_a_new_card_goes_to_the_end_of_its_list_with_its_labels(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("a", "todo", LOOP))
    payload = CardCreate(
        list_id="todo",
        title="New",
        priority="high",
        due_at="2026-11-10",
        labels=["Idea", "bug", " ", "fresh", "Idea", "idea"],
    )
    entry, replayed = w.service.create(HUMAN, BOARD_ID, LOOP, payload)
    assert replayed is False
    card = w.card("new-1")
    assert (card.position, card.priority, card.due_at, card.version) == (
        2048,
        "high",
        "2026-11-10T00:00:00Z",
        1,
    )
    assert (card.kind, card.required_actor, card.execution_mode) == ("manual", "any", "normal")
    assert (card.created_at, card.updated_at, card.loop_id) == (STAMP, STAMP, LOOP)
    assert w.state.labels["new-2"] == LabelsRow(id="new-2", name="fresh", color=NEW_LABEL_COLOR)
    assert [link.label_id for link in w.state.card_labels] == ["idea", "bug", "new-2"]
    assert isinstance(entry, dict)
    assert w.actions() == [("card.created", "new-1")]
    assert json.loads(w.state.activity[0].changes_json) == {
        "title": "New",
        "list_id": "todo",
        "loop_id": LOOP,
    }
    assert w.state.activity[0].id == "new-3"


def test_a_new_card_is_refused_where_it_cannot_belong(settings: Settings) -> None:
    w = world(settings)
    with pytest.raises(Conflict) as other:
        w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id="elsewhere", title="x"))
    assert (other.value.code, other.value.details) == ("loop_mismatch", {"list_id": "elsewhere"})
    for list_id in ("shelf", "missing"):
        with pytest.raises(ValidationFailure) as invalid:
            w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id=list_id, title="x"))
        assert invalid.value.details == {"list_id": list_id}
    with pytest.raises(Forbidden):
        w.service.create(READER, BOARD_ID, LOOP, CardCreate(list_id="todo", title="x"))
    assert w.state.cards == {}
    assert w.store.commits == 0


@pytest.mark.parametrize(
    ("loop", "code", "message"),
    [
        (
            loop_row(LOOP, stage="replanning").__replace__(current_plan_id="p"),
            "plan_change_required",
            "This Loop's plan is not executing; amend the plan or wait for it to run",
        ),
        (
            loop_row(LOOP, stage="roadmap_review").__replace__(current_plan_id="p"),
            "plan_change_required",
            "This Loop's plan is not executing; amend the plan or wait for it to run",
        ),
        (
            loop_row(LOOP, completed_at=STAMP),
            "loop_read_only",
            "This Loop is completed and read-only",
        ),
        (
            loop_row(LOOP, stage="completed"),
            "loop_read_only",
            "This Loop is completed and read-only",
        ),
        (loop_row(LOOP, archived_at=STAMP), "loop_read_only", "This Loop is not editable"),
        (loop_row(LOOP, cancelled_at=STAMP), "loop_read_only", "This Loop is not editable"),
    ],
)
def test_a_planned_or_finished_loop_takes_no_new_card(
    settings: Settings, loop: LoopsRow, code: str, message: str
) -> None:
    w = world(settings, loop)
    payload = CardCreate(list_id="todo", title="x")
    with pytest.raises(Conflict) as refused:
        w.service.create(HUMAN, BOARD_ID, LOOP, payload)
    assert (refused.value.code, refused.value.message) == (code, message)
    with pytest.raises(Conflict):
        w.service.bulk_create(HUMAN, BOARD_ID, LOOP, BulkCardCreate(cards=[payload]))
    assert w.state.cards == {}


@pytest.mark.parametrize("stage", ["ready", "in_progress", "awaiting_qa"])
def test_an_executing_loop_takes_unplanned_work_keyed_after_every_earlier_one(
    settings: Settings, stage: str
) -> None:
    w = world(settings, loop_row(LOOP, stage=stage).__replace__(current_plan_id="p"))
    first, _ = w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id="todo", title="One"))
    second, _ = w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Two"))
    assert (first["ticket_key"], second["ticket_key"]) == ("L-1-UNP-001", "L-1-UNP-002")
    assert {w.card(str(first["id"])).kind, w.card(str(second["id"])).kind} == {"manual"}
    # An archived one keeps its key, so the next never reuses it.
    w.service.archive(HUMAN, BOARD_ID, LOOP, str(second["id"]))
    third, _ = w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Three"))
    assert third["ticket_key"] == "L-1-UNP-003"


def test_a_loop_without_a_plan_keys_no_manual_card(settings: Settings) -> None:
    w = world(settings)
    entry, _ = w.service.create(HUMAN, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Plain"))
    assert entry["ticket_key"] is None


def test_a_replayed_card_key_answers_the_stored_card(settings: Settings) -> None:
    w = world(settings)
    payload = CardCreate(list_id="todo", title="Once")
    first, _ = w.service.create(HUMAN, BOARD_ID, LOOP, payload, idempotency_key="k")
    again, replayed = w.service.create(HUMAN, BOARD_ID, LOOP, payload, idempotency_key="k")
    assert replayed is True
    assert again == json.loads(json.dumps(first))
    assert len(w.state.cards) == 1
    with pytest.raises(Conflict) as reused:
        w.service.create(
            HUMAN, BOARD_ID, LOOP, CardCreate(list_id="todo", title="Twice"), idempotency_key="k"
        )
    assert reused.value.code == "idempotency_key_reused"


def test_a_bulk_request_keeps_the_cards_that_work_and_reports_the_others(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    w = world(settings)
    # The third card's new label gets an id that is taken: SQLite would refuse the row after the
    # card itself was written, and the savepoint undoes that card only.
    w.ids.clash = {4: "bug"}
    payload = BulkCardCreate(
        cards=[
            CardCreate(list_id="todo", title="One"),
            CardCreate(list_id="elsewhere", title="Wrong loop"),
            CardCreate(list_id="todo", title="Broken", labels=["brand-new"]),
            CardCreate(list_id="doing", title="Two"),
        ]
    )
    with caplog.at_level(logging.ERROR, logger="tralala.cards"):
        result, replayed = w.service.bulk_create(HUMAN, BOARD_ID, LOOP, payload)
    assert replayed is False
    assert isinstance(result, dict)
    assert [card.title for card in w.state.cards.values()] == ["One", "Two"]
    assert "brand-new" not in {label.name for label in w.state.labels.values()}
    assert result["failed"] == [
        {"index": 1, "code": "card_create_failed", "message": "The column belongs to another Loop"},
        {"index": 2, "code": "card_create_failed", "message": "Card could not be created"},
    ]
    assert [action for action, _ in w.actions()] == ["card.created", "card.created"]
    assert "bulk card creation failed" in caplog.text
    limited = world(settings.model_copy(update={"bulk_limit": 3}))
    with pytest.raises(ValidationFailure) as limit:
        limited.service.bulk_create(HUMAN, BOARD_ID, LOOP, payload)
    assert limit.value.details == {"limit": 3}
    assert limited.state.cards == {}


def test_a_replayed_bulk_key_answers_the_stored_result(settings: Settings) -> None:
    w = world(settings)
    payload = BulkCardCreate(cards=[CardCreate(list_id="todo", title="One")])
    first, _ = w.service.bulk_create(HUMAN, BOARD_ID, LOOP, payload, idempotency_key="b")
    again, replayed = w.service.bulk_create(HUMAN, BOARD_ID, LOOP, payload, idempotency_key="b")
    assert replayed is True
    assert again == json.loads(json.dumps(first))
    assert len(w.state.cards) == 1


# --- update ---------------------------------------------------------------------------------------


def test_an_update_writes_the_changed_fields_and_logs_them_in_order(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP).__replace__(due_at="2026-11-01T00:00:00Z"))
    w.state.card_labels = [CardLabelsRow(card_id="c", label_id="bug")]
    update = CardUpdate(
        version=1,
        title="Renamed",
        description="Text",
        priority="low",
        due_at="2026-11-20",
        labels=["Idea"],
    )
    entry = w.service.update(HUMAN, BOARD_ID, LOOP, "c", update)
    card = w.card("c")
    assert (card.title, card.description, card.priority, card.due_at) == (
        "Renamed",
        "Text",
        "low",
        "2026-11-20T00:00:00Z",
    )
    assert (card.version, card.updated_at) == (2, STAMP)
    assert [label["name"] for label in entry["labels"]] == ["Idea"]
    assert json.loads(w.state.activity[0].changes_json) == {
        "title": {"before": "Card c", "after": "Renamed"},
        "description": {"changed": True},
        "priority": {"before": "medium", "after": "low"},
        "due_at": {"before": "2026-11-01T00:00:00Z", "after": "2026-11-20T00:00:00Z"},
        "labels": {"after": ["Idea"]},
    }
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=2, clear_due_at=True))
    assert w.card("c").due_at is None
    assert w.card("c").version == 3


def test_an_update_that_changes_nothing_writes_nothing_and_labels_alone_keep_the_version(
    settings: Settings,
) -> None:
    w = world(settings, loop_row(LOOP, stage="planning"))
    put(w, card_row("c", "todo", LOOP))
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, title="Card c"))
    assert w.card("c").version == 1
    assert w.state.activity == []
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, labels=["Bug"]))
    assert w.card("c").version == 1
    assert w.actions() == [("card.updated", "c")]
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, title="Renamed"))
    assert w.state.loops[LOOP].stage == "planning"


def test_an_update_checks_the_version_the_owner_and_a_read_only_loop(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    with pytest.raises(VersionConflict) as stale:
        w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=2, title="x"))
    assert stale.value.details == {"expected_version": 2, "current_version": 1}
    assert stale.value.message == "Card was modified by another actor"
    w.state.cards["c"] = w.card("c").__replace__(version=3)
    with pytest.raises(VersionConflict):
        w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, title="x"))
    w.state.cards["c"] = w.card("c").__replace__(version=1)
    with pytest.raises(Conflict) as mismatch:
        w.service.update(HUMAN, BOARD_ID, OTHER, "c", CardUpdate(version=1, title="x"))
    assert mismatch.value.code == "loop_mismatch"
    w.state.loops[LOOP] = loop_row(LOOP, completed_at=STAMP)
    with pytest.raises(Conflict) as done:
        w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, title="x"))
    assert done.value.code == "loop_read_only"
    assert w.card("c").title == "Card c"


def test_the_approved_work_definition_is_not_edited_through_a_card(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("t", "todo", LOOP, plan_item_id="item").__replace__(ticket_key="K-1"))
    for update, field in (
        (CardUpdate(version=1, title="Other"), "title"),
        (CardUpdate(version=1, description="Other"), "description"),
    ):
        with pytest.raises(Conflict) as refused:
            w.service.update(HUMAN, BOARD_ID, LOOP, "t", update)
        assert refused.value.code == "plan_change_required"
        assert refused.value.details == {"field": field, "ticket_key": "K-1"}
    w.service.update(
        HUMAN, BOARD_ID, LOOP, "t", CardUpdate(version=1, title="Card t", priority="low")
    )
    assert w.card("t").priority == "low"


def test_completing_a_card_without_a_plan_records_it_and_refreshes_the_stage(
    settings: Settings,
) -> None:
    w = world(settings, loop_row(LOOP, stage="planning"))
    put(w, card_row("c", "todo", LOOP))
    put(w, card_row("h", "todo", LOOP).__replace__(required_actor="human"))
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, completed=True))
    assert (w.card("c").completed_at, w.card("c").human_confirmed_at) == (STAMP, None)
    assert w.state.loops[LOOP].stage == "draft"
    w.service.update(HUMAN, BOARD_ID, LOOP, "h", CardUpdate(version=1, completed=True))
    card = w.card("h")
    assert (card.completed_at, card.human_confirmed_at, card.human_confirmed_by_actor_id) == (
        STAMP,
        STAMP,
        "actor-1",
    )
    assert json.loads(w.state.activity[-1].changes_json) == {
        "completed": {"before": False, "after": True},
        "human_confirmation": {"actor_id": "actor-1"},
    }
    w.service.update(HUMAN, BOARD_ID, LOOP, "h", CardUpdate(version=2, completed=True))
    w.service.update(AGENT, BOARD_ID, LOOP, "h", CardUpdate(version=2, completed=True))
    assert w.card("h").version == 2


def test_completion_faces_the_human_the_archive_the_stage_and_readiness_gates(
    settings: Settings,
) -> None:
    w = world(settings, loop_row(LOOP, stage="draft").__replace__(current_plan_id="p"))
    put(w, card_row("h", "todo", LOOP).__replace__(required_actor="human", ticket_key="K-1"))
    put(w, card_row("t", "todo", LOOP, plan_item_id="item").__replace__(ticket_key="K-2"))
    put(w, card_row("old", "todo", LOOP, archived_at=CREATED))
    complete = CardUpdate(version=1, completed=True)
    with pytest.raises(Conflict) as archived:
        w.service.update(HUMAN, BOARD_ID, LOOP, "old", complete)
    assert (archived.value.code, archived.value.details) == (
        "ticket_blocked",
        {"ticket_id": "old"},
    )
    with pytest.raises(Conflict) as stage:
        w.service.update(HUMAN, BOARD_ID, LOOP, "t", complete)
    assert stage.value.code == "approval_required"
    with pytest.raises(Conflict) as manual:
        w.service.update(HUMAN, BOARD_ID, LOOP, "h", complete)
    assert manual.value.code == "approval_required"
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(stage="ready")
    with pytest.raises(Forbidden) as agent:
        w.service.update(AGENT, BOARD_ID, LOOP, "h", complete)
    assert agent.value.code == "human_action_required"
    w.views.items = [readiness_item("t", ready=False, blockers=(BLOCKER,))]
    with pytest.raises(Conflict) as blocked:
        w.service.update(HUMAN, BOARD_ID, LOOP, "t", complete)
    assert blocked.value.code == "ticket_blocked"
    assert blocked.value.details == {"blockers": [BLOCKER], "ticket_key": "K-2"}
    assert all(card.completed_at is None for card in w.state.cards.values())
    w.views.items = [readiness_item("t")]
    w.service.update(AGENT, BOARD_ID, LOOP, "t", complete)
    assert w.card("t").completed_at == STAMP


def test_reopening_work_supersedes_open_qa_and_clears_the_delivery_approvals(
    settings: Settings,
) -> None:
    loop = loop_row(LOOP, stage="awaiting_qa").__replace__(
        implementation_approval_id="impl", qa_approval_id="qa", analysis_approval_id="an"
    )
    w = world(settings, loop)
    put(
        w,
        card_row("c", "todo", LOOP).__replace__(
            completed_at=CREATED, human_confirmed_at=CREATED, human_confirmed_by_actor_id="p"
        ),
    )
    w.state.qa_cycles = {
        "open": qa_cycle_row("open", LOOP, 2, status="in_progress"),
        "done": qa_cycle_row("done", LOOP, 1, status="rejected"),
        "other": qa_cycle_row("other", OTHER, 1, status="pending"),
    }
    w.state.plans = {"p": plan_row("p", LOOP)}
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, completed=False))
    card = w.card("c")
    assert (card.completed_at, card.human_confirmed_at, card.human_confirmed_by_actor_id) == (
        None,
        None,
        None,
    )
    statuses = {cycle.id: cycle.status for cycle in w.state.qa_cycles.values()}
    assert statuses == {"open": "superseded", "done": "rejected", "other": "pending"}
    assert w.state.qa_cycles["open"].updated_at == STAMP
    after = w.state.loops[LOOP]
    assert (after.implementation_approval_id, after.qa_approval_id) == (None, None)
    assert after.analysis_approval_id == "an"
    assert after.stage == "replanning"
    assert w.actions() == [("loop.reopened_work", "c"), ("card.updated", "c")]
    system = w.state.activity[0]
    assert (system.actor_id, system.actor_type, system.request_id) == ("system", "system", None)
    assert json.loads(system.changes_json) == {"revalidation_required": True}


@pytest.mark.parametrize(
    ("assignee", "expected"),
    [
        ("person", ("person", "user", "Grace")),
        ("helper", ("helper", "agent", "Helper")),
    ],
)
def test_a_person_or_an_enabled_agent_can_be_assigned(
    settings: Settings, assignee: str, expected: tuple[str, str, str]
) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, assignee_actor_id=assignee))
    card = w.card("c")
    assert (card.assignee_actor_id, card.assignee_type, card.assignee_name) == expected
    assert (card.assigned_at, card.assigned_by_actor_id, card.version) == (STAMP, "actor-1", 2)
    assert json.loads(w.state.activity[0].changes_json) == {
        "assignee": {
            "before": None,
            "after": expected[0],
            "name": expected[2],
            "type": expected[1],
        }
    }
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=2, assignee_actor_id=assignee))
    assert w.card("c").version == 2
    w.service.update(HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=2, clear_assignee=True))
    card = w.card("c")
    assert (card.assignee_actor_id, card.assignee_type, card.assigned_at, card.version) == (
        None,
        None,
        None,
        3,
    )


@pytest.mark.parametrize(
    ("assignee", "message"),
    [
        ("asleep", "Agent is disabled and cannot be assigned"),
        ("gone", "Assignee must be a human user or a registered agent"),
        ("nobody", "Assignee must be a human user or a registered agent"),
    ],
)
def test_a_disabled_or_unknown_assignee_is_refused(
    settings: Settings, assignee: str, message: str
) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    with pytest.raises(ValidationFailure) as refused:
        w.service.update(
            HUMAN, BOARD_ID, LOOP, "c", CardUpdate(version=1, assignee_actor_id=assignee)
        )
    assert (refused.value.message, refused.value.details) == (
        message,
        {"assignee_actor_id": assignee},
    )
    assert w.card("c").assignee_actor_id is None


# --- move, archive, restore -----------------------------------------------------------------------


def test_a_move_places_the_card_and_renumbers_when_no_gap_is_left(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("a", "todo", LOOP).__replace__(position=1))
    put(w, card_row("b", "todo", LOOP).__replace__(position=2))
    put(w, card_row("m", "doing", LOOP))
    entry = w.service.move(
        HUMAN, BOARD_ID, LOOP, "m", CardMove(version=1, list_id="todo", position=1)
    )
    positions = {card.id: (card.list_id, card.position) for card in w.state.cards.values()}
    assert positions == {"a": ("todo", 1024), "b": ("todo", 2048), "m": ("todo", 1536)}
    assert (entry["version"], entry["updated_at"]) == (2, STAMP)
    assert w.card("a").version == 1
    assert json.loads(w.state.activity[0].changes_json) == {
        "from_list_id": "doing",
        "to_list_id": "todo",
        "position": 1,
    }
    w.service.move(HUMAN, BOARD_ID, LOOP, "m", CardMove(version=2, list_id="todo", position=99))
    assert w.card("m").position == 3072


def test_a_move_inside_the_same_list_leaves_the_card_out_of_its_neighbours(
    settings: Settings,
) -> None:
    w = world(settings)
    put(w, card_row("a", "todo", LOOP))
    put(w, card_row("b", "todo", LOOP).__replace__(position=2048))
    w.service.move(HUMAN, BOARD_ID, LOOP, "a", CardMove(version=1, list_id="todo", position=1))
    assert (w.card("a").position, w.card("b").position) == (3072, 2048)


def test_a_move_stays_inside_its_loop_and_checks_the_version(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP))
    with pytest.raises(Conflict) as other:
        w.service.move(
            HUMAN, BOARD_ID, LOOP, "c", CardMove(version=1, list_id="elsewhere", position=0)
        )
    assert (other.value.code, other.value.details) == ("loop_mismatch", {"target_loop_id": OTHER})
    for list_id in ("shelf", "missing"):
        with pytest.raises(ValidationFailure):
            w.service.move(
                HUMAN, BOARD_ID, LOOP, "c", CardMove(version=1, list_id=list_id, position=0)
            )
    with pytest.raises(VersionConflict):
        w.service.move(HUMAN, BOARD_ID, LOOP, "c", CardMove(version=5, list_id="doing", position=0))
    assert w.card("c").list_id == "todo"


def test_archive_and_restore_are_idempotent_and_restore_appends(settings: Settings) -> None:
    w = world(settings)
    put(w, card_row("c", "todo", LOOP, plan_item_id="item").__replace__(completed_at=CREATED))
    put(w, card_row("d", "todo", LOOP).__replace__(position=4096))
    entry = w.service.archive(HUMAN, BOARD_ID, LOOP, "c")
    assert (entry["archived_at"], entry["version"]) == (STAMP, 2)
    w.service.archive(HUMAN, BOARD_ID, LOOP, "c")
    assert json.loads(w.state.activity[0].changes_json) == {
        "completed": True,
        "still_required": True,
    }
    entry = w.service.restore(HUMAN, BOARD_ID, LOOP, "c")
    assert (entry["archived_at"], entry["position"], entry["version"]) == (None, 5120, 3)
    w.service.restore(HUMAN, BOARD_ID, LOOP, "c")
    assert w.actions() == [("card.archived", "c"), ("card.restored", "c")]
    w.service.archive(HUMAN, BOARD_ID, LOOP, "d")
    assert json.loads(w.state.activity[-1].changes_json) == {
        "completed": False,
        "still_required": False,
    }
    w.state.loops[LOOP] = loop_row(LOOP, cancelled_at=STAMP)
    for change in (w.service.archive, w.service.restore):
        with pytest.raises(Conflict) as refused:
            change(HUMAN, BOARD_ID, LOOP, "c")
        assert refused.value.code == "loop_read_only"
    with pytest.raises(Forbidden):
        w.service.archive(READER, BOARD_ID, LOOP, "c")
