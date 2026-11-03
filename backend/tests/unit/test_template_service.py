"""TemplateService's rules on an in-memory registry and board: names, the stored JSON, edits and the
snapshot of a Loop's layout.

The service runs its real code; only the repositories, both units of work, the board check, the
clock and the id source are replaced, by the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.core.context import ActorContext, scopes_for_role
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from app.db.generated.board import LabelsRow
from app.schemas.templates import TemplateCreate, TemplateFromBoard, TemplateLabel, TemplateUpdate
from app.services.boards import BoardService
from app.services.templates import BoardLookup, TemplateService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    list_row,
    loop_row,
)
from tests.unit.fakes.registry import (
    CREATED,
    FakeRegistryUnitOfWork,
    RegistryState,
    board_template_row,
)

NOW = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
ADMIN = ActorContext(
    actor_id="admin-1",
    actor_type="user",
    actor_name="Ada",
    scopes=scopes_for_role("admin"),
    role="admin",
)
WRITER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Robot", scopes=frozenset({"boards:write"})
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"boards:read"})
)


def board_service_is_what_template_service_needs(service: BoardService) -> BoardLookup:
    """Never called: pyright proves that the BoardService wired in Services fits BoardLookup."""
    return service


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


@dataclass(slots=True)
class Templates:
    registry: RegistryState
    store: FakeRegistryUnitOfWork
    board: BoardState
    checks: FakeBoardChecks
    service: TemplateService


@pytest.fixture
def templates() -> Templates:
    """Template ``scrum`` (Todo/Doing/Done, label Bug); a board whose Loop has lists and labels."""
    registry = RegistryState()
    registry.board_templates = {
        "scrum": board_template_row(
            "scrum",
            name="Scrum",
            lists_json='["Todo", "Doing", "Done"]',
            labels_json='[{"name": "Bug", "color": "#ff0000"}]',
        )
    }
    board = BoardState()
    board.loops = {LOOP: loop_row(LOOP), "other": loop_row("other")}
    rows = [
        list_row("l3", LOOP, 3072, name="Done"),
        list_row("l1", LOOP, 1024, name="Todo"),
        list_row("l2", LOOP, 2048, name=" todo "),
        list_row("gone", LOOP, 1536, name="Gone", archived_at=CREATED),
        list_row("x", "other", 512, name="Elsewhere"),
    ]
    board.lists = {row.id: row for row in rows}
    board.labels = {
        "b": LabelsRow(id="b", name="Bug", color="#ff0000"),
        "a": LabelsRow(id="a", name="Alpha", color="#123456"),
    }
    store = FakeRegistryUnitOfWork(registry)
    checks = FakeBoardChecks()
    service = TemplateService(
        store, FakeBoardUnitOfWork(board), checks, clock=lambda: NOW, new_id=Ids()
    )
    return Templates(registry, store, board, checks, service)


# --- the stored JSON -----------------------------------------------------------------------------


def test_an_entry_carries_its_lists_and_labels_parsed_never_the_stored_json(
    templates: Templates,
) -> None:
    entry = templates.service.get("scrum")
    assert entry == {
        "id": "scrum",
        "name": "Scrum",
        "description": "",
        "created_at": CREATED,
        "updated_at": CREATED,
        "lists": ["Todo", "Doing", "Done"],
        "labels": [{"name": "Bug", "color": "#ff0000"}],
        "list_count": 3,
    }
    assert list(entry) == list(templates.service.list()[0])


@pytest.mark.parametrize(
    ("lists_json", "labels_json", "lists", "labels"),
    [
        ("not json", "", [], []),
        ('{"a": 1}', '{"name": "x"}', [], []),
        (
            '["A", 2, null, "B"]',
            '[{"name": "L"}, {"color": "#111111"}, "x", {"name": 3}, {"name": "M", "color": ""}]',
            ["A", "B"],
            [{"name": "L", "color": "#64748b"}, {"name": "M", "color": "#64748b"}],
        ),
    ],
)
def test_stored_json_that_is_not_what_a_template_holds_reads_as_less(
    templates: Templates,
    lists_json: str,
    labels_json: str,
    lists: list[str],
    labels: list[dict[str, str]],
) -> None:
    templates.registry.board_templates["odd"] = board_template_row(
        "odd", name="Odd", lists_json=lists_json, labels_json=labels_json
    )
    entry = templates.service.get("odd")
    assert (entry["lists"], entry["labels"], entry["list_count"]) == (lists, labels, len(lists))


def test_the_list_is_by_name_without_regard_to_case(templates: Templates) -> None:
    templates.registry.board_templates["k"] = board_template_row("k", name="kanban")
    templates.registry.board_templates["a"] = board_template_row("a", name="Agile")
    assert [entry["name"] for entry in templates.service.list()] == ["Agile", "kanban", "Scrum"]


def test_an_unknown_template_is_not_found_or_cannot_be_resolved(templates: Templates) -> None:
    assert templates.service.find("nothing") is None
    with pytest.raises(NotFound):
        templates.service.get("nothing")
    with pytest.raises(ValidationFailure) as caught:
        templates.service.resolve("nothing")
    assert caught.value.details == {"template_id": "nothing"}
    assert templates.service.resolve("scrum")["lists"] == ["Todo", "Doing", "Done"]


# --- create, update, delete ----------------------------------------------------------------------


def test_a_new_template_stores_its_lists_and_labels_as_json(templates: Templates) -> None:
    payload = TemplateCreate(
        name="Kanban",
        description="Flow",
        lists=["Next", "Now"],
        labels=[TemplateLabel(name="Risk", color="#00ff00")],
    )
    entry = templates.service.create(WRITER, payload)
    row = templates.registry.board_templates["new-1"]
    assert json.loads(row.lists_json) == ["Next", "Now"]
    assert row.labels_json == json.dumps([{"name": "Risk", "color": "#00ff00"}])
    assert (row.created_at, row.updated_at, entry["list_count"]) == (NOW, NOW, 2)


@pytest.mark.parametrize(
    ("lists", "labels", "field"),
    [
        (["Todo", " todo "], [], "list"),
        (
            [],
            [
                TemplateLabel(name="Bug", color="#000000"),
                TemplateLabel(name="BUG", color="#000000"),
            ],
            "label",
        ),
    ],
)
def test_a_name_twice_in_one_template_is_refused(
    templates: Templates, lists: list[str], labels: list[TemplateLabel], field: str
) -> None:
    with pytest.raises(ValidationFailure, match=f"Duplicate {field} name") as caught:
        templates.service.create(WRITER, TemplateCreate(name="T", lists=lists, labels=labels))
    assert caught.value.details is not None
    assert templates.store.commits == 0


def test_a_name_another_template_has_in_any_case_is_taken(templates: Templates) -> None:
    with pytest.raises(Conflict) as caught:
        templates.service.create(WRITER, TemplateCreate(name="SCRUM"))
    assert (caught.value.code, caught.value.details) == ("template_name_taken", {"name": "SCRUM"})
    assert templates.store.rollbacks == 1


def test_an_edit_keeps_what_it_does_not_name(templates: Templates) -> None:
    entry = templates.service.update(WRITER, "scrum", TemplateUpdate(lists=["A", "B"]))
    assert (entry["name"], entry["lists"], entry["labels"]) == (
        "Scrum",
        ["A", "B"],
        [{"name": "Bug", "color": "#ff0000"}],
    )
    row = templates.registry.board_templates["scrum"]
    assert (row.created_at, row.updated_at) == (CREATED, NOW)
    entry = templates.service.update(
        WRITER,
        "scrum",
        TemplateUpdate(description="Kanban", labels=[TemplateLabel(name="X", color="#000000")]),
    )
    assert (entry["description"], entry["lists"], entry["labels"]) == (
        "Kanban",
        ["A", "B"],
        [{"name": "X", "color": "#000000"}],
    )


def test_an_empty_edit_changes_nothing(templates: Templates) -> None:
    assert templates.service.update(WRITER, "scrum", TemplateUpdate())["updated_at"] == CREATED
    assert templates.store.commits == 0


def test_an_edit_is_checked_like_a_new_template(templates: Templates) -> None:
    templates.registry.board_templates["k"] = board_template_row("k", name="Kanban")
    with pytest.raises(ValidationFailure):
        templates.service.update(WRITER, "scrum", TemplateUpdate(lists=["A", "a"]))
    with pytest.raises(Conflict) as caught:
        templates.service.update(WRITER, "scrum", TemplateUpdate(name="KANBAN"))
    assert caught.value.details == {"name": "KANBAN"}
    with pytest.raises(NotFound):
        templates.service.update(WRITER, "nothing", TemplateUpdate(name="x"))


def test_deleting_needs_boards_admin(templates: Templates) -> None:
    with pytest.raises(Forbidden):
        templates.service.delete(WRITER, "scrum")
    templates.service.delete(ADMIN, "scrum")
    assert templates.registry.board_templates == {}
    with pytest.raises(NotFound):
        templates.service.delete(ADMIN, "scrum")


def test_writing_needs_boards_write(templates: Templates) -> None:
    with pytest.raises(Forbidden):
        templates.service.create(READER, TemplateCreate(name="T"))
    with pytest.raises(Forbidden):
        templates.service.update(READER, "scrum", TemplateUpdate(name="T"))
    with pytest.raises(Forbidden):
        templates.service.create_from_loop(READER, BOARD_ID, LOOP, TemplateFromBoard(name="T"))


# --- a Loop's layout -----------------------------------------------------------------------------


def test_a_loop_snapshot_takes_its_open_lists_in_order_once_and_every_board_label(
    templates: Templates,
) -> None:
    entry = templates.service.create_from_loop(
        WRITER, BOARD_ID, LOOP, TemplateFromBoard(name="From loop", description="Snapshot")
    )
    assert (entry["name"], entry["description"]) == ("From loop", "Snapshot")
    assert entry["lists"] == ["Todo", "Done"]
    assert entry["labels"] == [
        {"name": "Alpha", "color": "#123456"},
        {"name": "Bug", "color": "#ff0000"},
    ]
    assert templates.checks.calls == [("require_row", BOARD_ID)]


def test_lists_on_one_position_are_taken_in_the_order_they_were_made(
    templates: Templates,
) -> None:
    templates.board.lists = {
        "late": list_row("late", LOOP, 1024, name="Late").__replace__(
            created_at="2026-11-02T00:00:00Z"
        ),
        "early": list_row("early", LOOP, 1024, name="Early"),
    }
    entry = templates.service.create_from_loop(WRITER, BOARD_ID, LOOP, TemplateFromBoard(name="T"))
    assert entry["lists"] == ["Early", "Late"]


def test_a_snapshot_needs_a_registered_board_and_a_loop_of_it(templates: Templates) -> None:
    with pytest.raises(NotFound) as loop:
        templates.service.create_from_loop(WRITER, BOARD_ID, "nothing", TemplateFromBoard(name="T"))
    assert loop.value.code == "loop_not_found"
    templates.checks.unregistered = frozenset({BOARD_ID})
    with pytest.raises(NotFound, match="Board not found"):
        templates.service.create_from_loop(WRITER, BOARD_ID, LOOP, TemplateFromBoard(name="T"))
    assert templates.registry.board_templates.keys() == {"scrum"}


def test_a_snapshot_under_a_taken_name_is_refused(templates: Templates) -> None:
    with pytest.raises(Conflict):
        templates.service.create_from_loop(
            WRITER, BOARD_ID, LOOP, TemplateFromBoard(name="scrum")
        )
