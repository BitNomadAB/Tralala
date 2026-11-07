"""BoardService's rules on an in-memory registry and in-memory board databases: the board row's
lifecycle, idempotent creation, the board list, duplication, export, import and deletion.

The service runs its real code, with the real AgentService, RepositoryService and TemplateService
beside it; only the repositories, both units of work, the board files (a temporary directory whose
database files hold markers instead of SQLite pages), the migrator, the counters, the clock and the
id source are replaced, by the typed fakes in ``tests/unit/fakes``.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.context import ActorContext, scopes_for_role
from app.core.errors import (
    BoardUnreadable,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    ValidationFailure,
)
from app.db.generated.board import BoardLoopDefaultsRow, LabelsRow
from app.db.generated.registry import BoardRepositoriesRow, IdempotencyRecordsRow
from app.repositories.board_files import DatabaseProblem, ProblemReason
from app.schemas.boards import BoardCreate, BoardUpdate, RepositoryPaths
from app.services.agents import AgentService
from app.services.board_stats import BoardStatsCache
from app.services.boards import (
    IMPORT_REFUSALS,
    BoardCounters,
    BoardSchema,
    BoardService,
    Counts,
)
from app.services.lists import BoardChecks
from app.services.repo_mirror import MirrorService
from app.services.repositories import RepositoryService
from app.services.templates import TemplateService
from tests.unit.fakes.board import FakeCounterRepository, list_row, loop_row
from tests.unit.fakes.board_files import (
    FakeBoardDatabases,
    as_files,
    as_migrator,
    as_unit_of_work,
)
from tests.unit.fakes.mirror import FakeGit, FakeMirror, FakeMirrorFiles
from tests.unit.fakes.registry import (
    CREATED,
    ConstraintError,
    FakeRegistryUnitOfWork,
    RegistryState,
    agent_row,
    board_repository_row,
    board_row,
    board_template_row,
    repository_row,
    role_template_row,
)
from tests.unit.log_lines import events

MOMENT = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
NOW = "2026-11-03T10:00:00Z"
HEAD = "0010_generation_run_phase"
SOURCE = "6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
KEYS = [
    "id",
    "name",
    "description",
    "status",
    "created_at",
    "updated_at",
    "archived_at",
    "schema_version",
    "schema_revision",
    "loop_count",
    "list_count",
    "card_count",
    "repository_ids",
    "agent_ids",
    "repository_paths",
]
ADMIN = ActorContext(
    actor_id="admin-1",
    actor_type="user",
    actor_name="Ada",
    scopes=scopes_for_role("admin"),
    request_id="req-1",
    role="admin",
)
WRITER = ActorContext(
    actor_id="agent-1", actor_type="agent", actor_name="Robot", scopes=frozenset({"boards:write"})
)
READER = ActorContext(
    actor_id="agent-2", actor_type="agent", actor_name="Reader", scopes=frozenset({"boards:read"})
)


def uuid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def board_service_is_what_list_service_needs(service: BoardService) -> BoardChecks:
    """Never called: pyright proves that BoardService still fits ListService's checks."""
    return service


class Ids:
    """UUID-shaped ids in call order: a new board's id names its directory."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return uuid(self.issued)


class Clock:
    def __init__(self) -> None:
        self.moment = MOMENT

    def __call__(self) -> datetime:
        return self.moment


@dataclass(slots=True)
class FakeCounters:
    """The dashboard counters, measured from the fake databases on every call."""

    databases: FakeBoardDatabases
    batches: list[list[str]] = field(default_factory=list[list[str]])
    singles: list[str] = field(default_factory=list[str])

    def _measure(self, board_id: str) -> Counts:
        state = self.databases.states.get(board_id)
        if state is None:
            return 0, 0, 0
        counts = FakeCounterRepository(state).counts()
        return counts.loops, counts.lists, counts.cards

    def counts(self, board_id: str) -> Counts:
        self.singles.append(board_id)
        return self._measure(board_id)

    def counts_for(self, board_ids: list[str]) -> dict[str, Counts]:
        self.batches.append(list(board_ids))
        return {board_id: self._measure(board_id) for board_id in dict.fromkeys(board_ids)}


def as_counters(counters: FakeCounters) -> BoardCounters:
    return counters


@dataclass(slots=True)
class Boards:
    registry: RegistryState
    store: FakeRegistryUnitOfWork
    databases: FakeBoardDatabases
    counters: FakeCounters
    settings: Settings
    clock: Clock
    service: BoardService


@pytest.fixture
def boards(settings: Settings, tmp_path: Path) -> Boards:
    """One active board ``SOURCE`` with a Loop, two lists and an attachment; a template, two
    repositories and two agents to choose from."""
    configured = settings.model_copy(update={"data_dir": tmp_path})
    registry = RegistryState()
    registry.boards[SOURCE] = board_row(SOURCE, name="Source").__replace__(
        description="The original"
    )
    registry.board_templates["scrum"] = board_template_row(
        "scrum",
        name="Scrum",
        lists_json='["Todo", "Doing", "Done"]',
        labels_json='[{"name": "Bug", "color": "#ff0000"}]',
    ).__replace__(description="Sprint work")
    registry.role_templates["builder"] = role_template_row("builder")
    registry.role_templates["org"] = role_template_row("org", scope="organisation")
    registry.agents["agent-a"] = agent_row("agent-a", role_template_id="builder")
    registry.agents["agent-b"] = agent_row("agent-b", role_template_id="builder")
    registry.agents["planner"] = agent_row("planner", role_template_id="org")
    registry.code_repositories["repo-a"] = repository_row("repo-a")
    registry.code_repositories["repo-b"] = repository_row("repo-b")
    store = FakeRegistryUnitOfWork(registry)
    databases = FakeBoardDatabases(configured.boards_dir)
    databases.create_database(SOURCE, "The original")
    source = databases.states[SOURCE]
    source.loops = {"loop": loop_row("loop")}
    source.lists = {
        "todo": list_row("todo", "loop", 1024, name="Todo"),
        "done": list_row("done", "loop", 2048, name="Done"),
    }
    attachments = databases.attachments_dir(SOURCE)
    attachments.mkdir(parents=True)
    (attachments / "a1.bin").write_bytes(b"first")
    counters = FakeCounters(databases)
    clock = Clock()
    service = BoardService(
        configured,
        store,
        as_unit_of_work(databases),
        as_files(databases),
        migrations=as_migrator(databases),
        schema=BoardSchema(head_revision=HEAD, version=10),
        stats=as_counters(counters),
        agents=AgentService(configured, store),
        repositories=RepositoryService(configured, store),
        clock=clock,
        new_id=Ids(),
    )
    service.templates = TemplateService(store, as_unit_of_work(databases), service)
    return Boards(registry, store, databases, counters, configured, clock, service)


def link(board_id: str, repository_id: str, created_at: str = CREATED) -> BoardRepositoriesRow:
    return board_repository_row(board_id, repository_id, created_at=created_at)


# --- the registry row ----------------------------------------------------------------------------


def test_a_board_is_found_by_its_canonical_id_and_anything_else_is_not_found(
    boards: Boards,
) -> None:
    assert boards.service.require_row(SOURCE.upper()).id == SOURCE
    for unknown in (uuid(99), "not-a-uuid", "", "../etc"):
        with pytest.raises(NotFound, match="Board not found"):
            boards.service.require_row(unknown)


def test_an_entry_is_the_row_its_counters_and_its_selections_in_the_former_key_order(
    boards: Boards,
) -> None:
    boards.registry.repository_links = {
        (SOURCE, "repo-b"): link(SOURCE, "repo-b", "2026-11-01T08:00:00Z"),
        (SOURCE, "repo-a"): link(SOURCE, "repo-a", "2026-11-01T09:00:00Z"),
    }
    boards.service.agents.set_board_agents(SOURCE, ["agent-b", "agent-a"])
    entry = boards.service.get(SOURCE)
    assert list(entry) == KEYS
    assert entry == {
        "id": SOURCE,
        "name": "Source",
        "description": "The original",
        "status": "active",
        "created_at": CREATED,
        "updated_at": CREATED,
        "archived_at": None,
        "schema_version": 1,
        "schema_revision": None,
        "loop_count": 1,
        "list_count": 2,
        "card_count": 0,
        "repository_ids": ["repo-b", "repo-a"],
        # Chosen at the same moment, so by id.
        "agent_ids": ["agent-a", "agent-b"],
        "repository_paths": {},
    }
    assert boards.counters.singles == [SOURCE]


def test_ensure_active_lets_only_an_active_board_with_a_database_take_writes(
    boards: Boards,
) -> None:
    assert boards.service.ensure_active(SOURCE).id == SOURCE
    cases = [
        ("archived", "board_archived", None),
        ("migration_failed", "board_migration_failed", None),
        ("maintenance", "conflict", {"status": "maintenance"}),
        ("error", "conflict", {"status": "error"}),
    ]
    for status, code, details in cases:
        boards.registry.boards[SOURCE] = boards.registry.boards[SOURCE].__replace__(status=status)
        with pytest.raises(Conflict) as raised:
            boards.service.ensure_active(SOURCE)
        assert raised.value.code == code
        if details is not None:
            assert raised.value.details == details
    boards.registry.boards[uuid(7)] = board_row(uuid(7))
    with pytest.raises(NotFound, match="Board database not found"):
        boards.service.ensure_active(uuid(7))


# --- the board list ------------------------------------------------------------------------------


def _three(boards: Boards) -> None:
    boards.registry.boards = {
        uuid(1): board_row(uuid(1), name="beta").__replace__(
            description="has CATS", updated_at="2026-11-01T10:00:00Z", status="archived"
        ),
        uuid(2): board_row(uuid(2), name="Alpha").__replace__(updated_at="2026-11-02T10:00:00Z"),
        uuid(3): board_row(uuid(3), name="alpha").__replace__(updated_at="2026-11-02T10:00:00Z"),
    }


def test_the_list_filters_by_status_and_by_text_in_the_name_or_description(
    boards: Boards,
) -> None:
    _three(boards)
    entries, total = boards.service.list(status="archived")
    assert ([entry["id"] for entry in entries], total) == ([uuid(1)], 1)
    entries, total = boards.service.list(q="cat")
    assert ([entry["id"] for entry in entries], total) == ([uuid(1)], 1)
    entries, total = boards.service.list(q="ALPHA")
    assert sorted(entry["id"] for entry in entries) == [uuid(2), uuid(3)]
    entries, total = boards.service.list(q="%")
    assert total == 3
    entries, total = boards.service.list(q="a_p")
    assert total == 2
    entries, total = boards.service.list(q="", status="")
    assert total == 3


def test_the_list_refuses_a_status_it_does_not_know(boards: Boards) -> None:
    with pytest.raises(ValidationFailure) as raised:
        boards.service.list(status="deleted")
    assert raised.value.details == {
        "allowed": ["active", "archived", "error", "maintenance", "migration_failed"]
    }


def test_the_list_sorts_by_an_allowed_column_then_by_name_and_pages(boards: Boards) -> None:
    _three(boards)
    entries, _ = boards.service.list()
    assert [entry["name"] for entry in entries] == ["Alpha", "alpha", "beta"]
    entries, _ = boards.service.list(order="ASC")
    assert [entry["name"] for entry in entries] == ["beta", "Alpha", "alpha"]
    entries, _ = boards.service.list(sort="name", order="asc")
    assert [entry["name"] for entry in entries] == ["Alpha", "alpha", "beta"]
    entries, _ = boards.service.list(sort="name; DROP TABLE boards", order="desc")
    assert [entry["name"] for entry in entries] == ["Alpha", "alpha", "beta"]
    entries, total = boards.service.list(sort="name", order="asc", limit=1, offset=1)
    assert ([entry["name"] for entry in entries], total) == (["alpha"], 3)


def test_the_list_reads_every_counter_of_a_page_in_one_lookup_or_none_at_all(
    boards: Boards,
) -> None:
    boards.registry.boards[uuid(2)] = board_row(uuid(2), name="Empty")
    boards.registry.repository_links = {(SOURCE, "repo-a"): link(SOURCE, "repo-a")}
    boards.service.agents.set_board_agents(uuid(2), ["agent-a"])
    entries, _ = boards.service.list(sort="name", order="asc")
    assert boards.counters.batches == [[uuid(2), SOURCE]]
    assert boards.counters.singles == []
    found = [(item["list_count"], item["repository_ids"], item["agent_ids"]) for item in entries]
    assert found == [(0, [], ["agent-a"]), (2, ["repo-a"], [])]
    entries, _ = boards.service.list(sort="name", order="asc", with_counts=False)
    assert len(boards.counters.batches) == 1
    assert [entry["list_count"] for entry in entries] == [0, 0]


# --- creation ------------------------------------------------------------------------------------


def test_a_new_board_gets_its_database_columns_labels_and_links_and_then_turns_active(
    boards: Boards,
) -> None:
    payload = BoardCreate(
        name="Fresh", template_id="scrum", repository_ids=["repo-a"], agent_ids=["agent-a"]
    )
    entry, replayed = boards.service.create(ADMIN, payload)
    board_id = uuid(1)
    assert replayed is False
    assert entry == {
        "id": board_id,
        "name": "Fresh",
        "description": "Sprint work",
        "status": "active",
        "created_at": NOW,
        "updated_at": NOW,
        "archived_at": None,
        "schema_version": 10,
        "schema_revision": HEAD,
        "loop_count": 0,
        "list_count": 0,
        "card_count": 0,
        "repository_ids": ["repo-a"],
        "agent_ids": ["agent-a"],
        "repository_paths": {},
    }
    state = boards.databases.states[board_id]
    assert state.metadata is not None and state.metadata.description == "Sprint work"
    assert state.loop_defaults == BoardLoopDefaultsRow(
        id=1, column_names_json='["Todo", "Doing", "Done"]', updated_at=NOW
    )
    assert state.labels == {uuid(2): LabelsRow(id=uuid(2), name="Bug", color="#ff0000")}
    [logged] = state.activity
    assert (logged.id, logged.action, logged.entity_type, logged.entity_id) == (
        uuid(3),
        "board.created",
        "board",
        board_id,
    )
    assert (logged.actor_id, logged.actor_type, logged.request_id, logged.timestamp) == (
        "admin-1",
        "user",
        "req-1",
        NOW,
    )
    assert json.loads(logged.changes_json) == {
        "name": "Fresh",
        "loop_columns": ["Todo", "Doing", "Done"],
        "template_id": "scrum",
        "template_name": "Scrum",
    }
    assert boards.registry.idempotency == {}


@pytest.mark.parametrize(
    ("lists", "template_id", "expected"),
    [
        (["One", "Two"], "scrum", ["One", "Two"]),
        (None, "scrum", ["Todo", "Doing", "Done"]),
        (None, None, "settings"),
        ([], None, "settings"),
    ],
)
def test_a_new_boards_loop_columns_come_from_the_request_then_the_template_then_settings(
    boards: Boards, lists: list[str] | None, template_id: str | None, expected: object
) -> None:
    entry, _ = boards.service.create(
        ADMIN, BoardCreate(name="B", lists=lists, template_id=template_id)
    )
    state = boards.databases.states[str(entry["id"])]
    assert state.loop_defaults is not None
    names = boards.settings.list_names if expected == "settings" else expected
    assert json.loads(state.loop_defaults.column_names_json) == names
    changes = json.loads(state.activity[0].changes_json)
    assert ("template_id" in changes) is (template_id is not None)


def test_a_board_without_a_template_starts_with_the_default_area_labels(boards: Boards) -> None:
    """Where work belongs, never who does it; a template brings its own labels instead."""
    entry, _ = boards.service.create(ADMIN, BoardCreate(name="Areas"))
    state = boards.databases.states[str(entry["id"])]
    names = sorted(label.name for label in state.labels.values())
    assert names == sorted(boards.settings.label_names)
    assert {"Development", "UX", "QA", "Legal", "Economy", "Research"} <= set(names)
    assert not [name for name in names if "agent" in name.casefold()]
    bare = boards.settings.model_copy(update={"default_labels": ""})
    assert bare.label_names == []


def test_an_empty_template_list_falls_back_to_the_settings_and_a_description_wins(
    boards: Boards,
) -> None:
    boards.registry.board_templates["bare"] = board_template_row("bare", name="Bare")
    entry, _ = boards.service.create(ADMIN, BoardCreate(name="B", template_id="bare"))
    state = boards.databases.states[str(entry["id"])]
    assert state.loop_defaults is not None
    assert json.loads(state.loop_defaults.column_names_json) == boards.settings.list_names
    assert state.labels == {}
    entry, _ = boards.service.create(
        ADMIN, BoardCreate(name="C", description="Mine", template_id="scrum")
    )
    assert entry["description"] == "Mine"


def test_creation_checks_scope_template_and_selections_before_anything_is_written(
    boards: Boards,
) -> None:
    before = dict(boards.registry.boards)
    with pytest.raises(Forbidden):
        boards.service.create(READER, BoardCreate(name="B"))
    with pytest.raises(ValidationFailure, match="Template not found"):
        boards.service.create(ADMIN, BoardCreate(name="B", template_id="missing"))
    with pytest.raises(NotFound) as raised:
        boards.service.create(ADMIN, BoardCreate(name="B", repository_ids=["nothing"]))
    assert raised.value.code == "repository_not_found"
    with pytest.raises(ValidationFailure) as refused:
        boards.service.create(ADMIN, BoardCreate(name="B", agent_ids=["planner"]))
    assert refused.value.code == "agent_scope_organisation"
    boards.service.templates = None
    with pytest.raises(ValidationFailure, match="Board templates are unavailable"):
        boards.service.create(ADMIN, BoardCreate(name="B", template_id="scrum"))
    assert boards.registry.boards == before
    assert set(boards.databases.states) == {SOURCE}


def test_a_creation_that_fails_leaves_the_row_in_error_and_records_the_failure(
    boards: Boards,
) -> None:
    boards.registry.board_templates["clash"] = board_template_row(
        "clash",
        name="Clash",
        labels_json='[{"name": "Bug", "color": "#111111"}, {"name": "Bug", "color": "#222222"}]',
    )
    with pytest.raises(ConstraintError, match=r"labels\.name Bug exists"):
        boards.service.create(
            ADMIN, BoardCreate(name="B", template_id="clash"), idempotency_key="key-1"
        )
    board_id = uuid(1)
    assert boards.registry.boards[board_id].status == "error"
    record = boards.registry.idempotency[("admin-1", "key-1")]
    assert json.loads(record.response_json) == {
        "_pending": False,
        "board_id": board_id,
        "error": "creation_failed",
    }
    # The board's own writes were rolled back with the transaction that raised.
    assert boards.databases.states[board_id].labels == {}
    assert boards.databases.states[board_id].loop_defaults is None


def test_links_are_written_before_the_board_turns_active(boards: Boards) -> None:
    calls: list[str] = []
    service = boards.service
    original = service.agents

    class Failing:
        def validate_ids(self, agent_ids: list[str]) -> None:
            calls.append(f"validate {agent_ids}")

        def set_board_agents(self, board_id: str, agent_ids: list[str]) -> None:
            calls.append(f"{boards.registry.boards[board_id].status} {agent_ids}")
            # A retry arriving now finds the key reserved for this board.
            reserved = boards.registry.idempotency[("admin-1", "key-1")].response_json
            calls.append(reserved)
            raise RuntimeError("link failed")

        def agent_ids(self, board_id: str) -> list[str]:
            return original.agent_ids(board_id)

        def agent_ids_for_boards(self) -> dict[str, list[str]]:
            return original.agent_ids_for_boards()

    service.agents = Failing()
    with pytest.raises(RuntimeError, match="link failed"):
        service.create(ADMIN, BoardCreate(name="B", agent_ids=["agent-a"]), idempotency_key="key-1")
    assert calls == [
        "validate ['agent-a']",
        "maintenance ['agent-a']",
        json.dumps({"_pending": True, "board_id": uuid(1)}),
    ]
    assert boards.registry.boards[uuid(1)].status == "error"


# --- idempotent creation -------------------------------------------------------------------------


def test_a_replayed_key_answers_the_stored_board_without_creating_another(
    boards: Boards,
) -> None:
    payload = BoardCreate(name="Once")
    first, replayed = boards.service.create(ADMIN, payload, idempotency_key="key-1")
    assert replayed is False
    record = boards.registry.idempotency[("admin-1", "key-1")]
    assert json.loads(record.response_json) == first
    assert record.created_at == NOW
    expires = MOMENT + timedelta(seconds=boards.settings.idempotency_ttl_seconds)
    assert record.expires_at == expires.strftime("%Y-%m-%dT%H:%M:%SZ")
    first_id = str(first["id"])
    boards.registry.boards[first_id] = boards.registry.boards[first_id].__replace__(
        name="Renamed since"
    )
    again, replayed = boards.service.create(ADMIN, payload, idempotency_key="key-1")
    assert (again, replayed) == (first, True)
    assert len(boards.registry.boards) == 2
    # Another actor's key is its own.
    _, replayed = boards.service.create(WRITER, payload, idempotency_key="key-1")
    assert replayed is False
    assert len(boards.registry.boards) == 3


def test_a_key_reused_with_another_payload_is_refused(boards: Boards) -> None:
    boards.service.create(ADMIN, BoardCreate(name="Once"), idempotency_key="key-1")
    with pytest.raises(Conflict) as raised:
        boards.service.create(ADMIN, BoardCreate(name="Twice"), idempotency_key="key-1")
    assert raised.value.code == "idempotency_key_reused"


def _pending(boards: Boards, board_id: str) -> None:
    boards.registry.idempotency[("admin-1", "key-1")] = IdempotencyRecordsRow(
        actor_id="admin-1",
        idempotency_key="key-1",
        request_hash=_fingerprint(BoardCreate(name="Once")),
        response_json=json.dumps({"_pending": True, "board_id": board_id}),
        created_at=CREATED,
        expires_at="2026-11-02T09:00:00Z",
    )


def _fingerprint(payload: BoardCreate) -> str:
    from app.services.idempotency import request_fingerprint

    return request_fingerprint({"op": "board.create", "payload": payload.model_dump()})


def test_a_pending_key_answers_by_the_state_of_the_board_it_reserved(boards: Boards) -> None:
    _pending(boards, SOURCE)
    entry, replayed = boards.service.create(
        ADMIN, BoardCreate(name="Once"), idempotency_key="key-1"
    )
    assert replayed is True
    assert entry == boards.service.get(SOURCE)
    for status, code in (("error", "creation_failed"), ("maintenance", "creation_in_progress")):
        boards.registry.boards[SOURCE] = boards.registry.boards[SOURCE].__replace__(status=status)
        with pytest.raises(Conflict) as raised:
            boards.service.create(ADMIN, BoardCreate(name="Once"), idempotency_key="key-1")
        assert (raised.value.code, raised.value.details) == (code, {"board_id": SOURCE})
    for missing in (uuid(42), ""):
        _pending(boards, missing)
        with pytest.raises(Conflict) as raised:
            boards.service.create(ADMIN, BoardCreate(name="Once"), idempotency_key="key-1")
        assert (raised.value.code, raised.value.details) == (
            "creation_in_progress",
            {"board_id": missing},
        )
    assert len(boards.registry.boards) == 1


def test_an_expired_record_still_answers_a_board_creation(boards: Boards) -> None:
    first, _ = boards.service.create(ADMIN, BoardCreate(name="Once"), idempotency_key="key-1")
    boards.clock.moment = MOMENT + timedelta(days=30)
    again, replayed = boards.service.create(
        ADMIN, BoardCreate(name="Once"), idempotency_key="key-1"
    )
    assert (again, replayed) == (first, True)


# --- edits ---------------------------------------------------------------------------------------


def test_an_edit_writes_the_row_and_logs_what_changed(boards: Boards) -> None:
    boards.clock.moment = MOMENT + timedelta(minutes=5)
    payload = BoardUpdate(name="Renamed", description="New", repository_ids=["repo-b"])
    entry = boards.service.update(ADMIN, SOURCE, payload)
    assert (entry["name"], entry["description"], entry["updated_at"]) == (
        "Renamed",
        "New",
        "2026-11-03T10:05:00Z",
    )
    assert (entry["repository_ids"], entry["agent_ids"]) == (["repo-b"], [])
    [logged] = boards.databases.states[SOURCE].activity
    assert logged.action == "board.updated"
    assert json.loads(logged.changes_json) == {
        "before": {"name": "Source", "description": "The original"},
        "after": {"name": "Renamed", "description": "New"},
    }


def test_an_edit_without_changes_writes_nothing_and_selections_alone_are_relinked(
    boards: Boards,
) -> None:
    assert boards.service.update(ADMIN, SOURCE, BoardUpdate()) == boards.service.get(SOURCE)
    entry = boards.service.update(
        ADMIN, SOURCE, BoardUpdate(repository_ids=["repo-b", "repo-a"], agent_ids=["agent-b"])
    )
    assert (entry["repository_ids"], entry["agent_ids"]) == (["repo-a", "repo-b"], ["agent-b"])
    assert boards.registry.boards[SOURCE].updated_at == CREATED
    assert boards.databases.states[SOURCE].activity == []
    entry = boards.service.update(ADMIN, SOURCE, BoardUpdate(repository_ids=[], agent_ids=[]))
    assert (entry["repository_ids"], entry["agent_ids"]) == ([], [])


DOCS_ONLY = RepositoryPaths(focus_paths=["docs/**"], exclude_paths=["docs/old/*"])
DOCS_ONLY_OUT = {"focus_paths": ["docs/**"], "exclude_paths": ["docs/old/*"]}


def test_a_new_board_stores_and_names_the_globs_of_its_links(boards: Boards) -> None:
    payload = BoardCreate(
        name="Fresh", repository_ids=["repo-a", "repo-b"], repository_paths={"repo-b": DOCS_ONLY}
    )
    entry, _ = boards.service.create(ADMIN, payload)
    assert (entry["repository_ids"], entry["repository_paths"]) == (
        ["repo-a", "repo-b"],
        {"repo-b": DOCS_ONLY_OUT},
    )
    listed, _ = boards.service.list(sort="name", order="asc")
    assert [item["repository_paths"] for item in listed] == [{"repo-b": DOCS_ONLY_OUT}, {}]


def test_a_new_board_with_globs_for_a_repository_it_does_not_link_is_refused_first(
    boards: Boards,
) -> None:
    payload = BoardCreate(
        name="Fresh", repository_ids=["repo-a"], repository_paths={"repo-b": DOCS_ONLY}
    )
    with pytest.raises(ValidationFailure) as raised:
        boards.service.create(ADMIN, payload)
    assert raised.value.details == {"field": "repository_paths", "repository_ids": ["repo-b"]}
    assert list(boards.registry.boards) == [SOURCE]


def test_an_edit_with_globs_alone_keeps_the_selection_and_replaces_the_globs(
    boards: Boards,
) -> None:
    boards.service.update(ADMIN, SOURCE, BoardUpdate(repository_ids=["repo-a", "repo-b"]))
    entry = boards.service.update(
        ADMIN, SOURCE, BoardUpdate(repository_paths={"repo-a": DOCS_ONLY})
    )
    assert (entry["repository_ids"], entry["repository_paths"]) == (
        ["repo-a", "repo-b"],
        {"repo-a": DOCS_ONLY_OUT},
    )
    # A client that only knows repository_ids keeps the globs of what stays linked.
    entry = boards.service.update(
        ADMIN, SOURCE, BoardUpdate(name="Renamed", repository_ids=["repo-a"])
    )
    assert entry["repository_paths"] == {"repo-a": DOCS_ONLY_OUT}
    with pytest.raises(ValidationFailure) as raised:
        boards.service.update(ADMIN, SOURCE, BoardUpdate(repository_paths={"repo-b": DOCS_ONLY}))
    assert raised.value.details == {"field": "repository_paths", "repository_ids": ["repo-b"]}
    entry = boards.service.update(ADMIN, SOURCE, BoardUpdate(repository_paths={}))
    assert (entry["repository_ids"], entry["repository_paths"]) == (["repo-a"], {})


def test_an_edit_checks_its_selections_before_it_writes(boards: Boards) -> None:
    with pytest.raises(NotFound):
        boards.service.update(ADMIN, SOURCE, BoardUpdate(name="X", repository_ids=["nothing"]))
    with pytest.raises(NotFound):
        boards.service.update(ADMIN, SOURCE, BoardUpdate(name="X", agent_ids=["nothing"]))
    assert boards.registry.boards[SOURCE].name == "Source"
    with pytest.raises(Forbidden):
        boards.service.update(READER, SOURCE, BoardUpdate(name="X"))


def test_archiving_and_restoring_move_the_status_and_are_logged(boards: Boards) -> None:
    entry = boards.service.archive(ADMIN, SOURCE)
    assert (entry["status"], entry["archived_at"]) == ("archived", NOW)
    again = boards.service.archive(ADMIN, SOURCE)
    assert again == entry
    entry = boards.service.restore(ADMIN, SOURCE)
    assert (entry["status"], entry["archived_at"]) == ("active", None)
    with pytest.raises(Conflict, match="Only archived boards can be restored"):
        boards.service.restore(ADMIN, SOURCE)
    actions = [row.action for row in boards.databases.states[SOURCE].activity]
    assert actions == ["board.archived", "board.restored"]


def test_a_board_without_its_database_archives_silently_and_cannot_be_restored(
    boards: Boards,
) -> None:
    boards.registry.boards[uuid(7)] = board_row(uuid(7))
    assert boards.service.archive(ADMIN, uuid(7))["status"] == "archived"
    with pytest.raises(NotFound, match="Board database not found"):
        boards.service.restore(ADMIN, uuid(7))
    assert boards.registry.boards[uuid(7)].status == "archived"


@pytest.mark.parametrize(
    ("broken", "event"),
    [("unreadable", "board_database_unreadable"), ("unavailable", "board_schema_outdated")],
)
def test_a_board_whose_database_cannot_be_opened_is_archived_and_can_then_be_deleted(
    boards: Boards, caplog: pytest.LogCaptureFixture, broken: str, event: str
) -> None:
    # Was a 503 from the board's activity entry, after the row had already been archived.
    getattr(boards.databases, broken).add(SOURCE)
    with caplog.at_level(logging.WARNING, logger="tralala"):
        entry = boards.service.archive(ADMIN, SOURCE)
    assert (entry["status"], entry["archived_at"]) == ("archived", NOW)
    assert boards.registry.boards[SOURCE].status == "archived"
    assert events(caplog.records) == [
        {"event": event, "board_id": SOURCE, "skipped": "board_archived_activity"}
    ]
    assert boards.databases.states[SOURCE].activity == []
    boards.service.delete(ADMIN, SOURCE, "Source")
    assert SOURCE not in boards.registry.boards
    assert not boards.databases.path(SOURCE).exists()


# --- duplication ---------------------------------------------------------------------------------


def test_a_duplicate_carries_the_rows_and_files_and_claims_its_own_id(boards: Boards) -> None:
    entry = boards.service.duplicate(ADMIN, SOURCE)
    copy_id = uuid(1)
    assert (entry["id"], entry["name"], entry["description"], entry["status"]) == (
        copy_id,
        "Source (copy)",
        "The original",
        "active",
    )
    assert (entry["schema_revision"], entry["list_count"]) == (HEAD, 2)
    copied = boards.databases.states[copy_id]
    assert set(copied.lists) == {"todo", "done"}
    assert copied.metadata is not None
    assert (copied.metadata.id, copied.metadata.updated_at) == (copy_id, NOW)
    [logged] = copied.activity
    assert (logged.action, logged.entity_id) == ("board.duplicated", copy_id)
    assert json.loads(logged.changes_json) == {"source_board_id": SOURCE}
    assert (boards.databases.attachments_dir(copy_id) / "a1.bin").read_bytes() == b"first"
    # The source keeps its own id and gains nothing.
    source = boards.databases.states[SOURCE]
    assert source.metadata is not None and source.metadata.id == SOURCE
    assert source.activity == []
    assert boards.service.duplicate(ADMIN, SOURCE, "Named")["name"] == "Named"


def test_a_duplicate_that_fails_is_left_in_error(boards: Boards) -> None:
    boards.databases.unavailable.add(uuid(1))
    with pytest.raises(ServiceUnavailable):
        boards.service.duplicate(ADMIN, SOURCE)
    assert boards.registry.boards[uuid(1)].status == "error"
    boards.registry.boards[uuid(9)] = board_row(uuid(9))
    with pytest.raises(NotFound, match="Board database not found"):
        boards.service.duplicate(ADMIN, uuid(9))


# --- deletion ------------------------------------------------------------------------------------


def test_only_an_archived_board_confirmed_by_name_is_deleted_with_all_its_files(
    boards: Boards,
) -> None:
    backups = boards.settings.backups_dir / SOURCE
    backups.mkdir(parents=True)
    (backups / "old.sqlite").write_bytes(b"x")
    with pytest.raises(Forbidden):
        boards.service.delete(WRITER, SOURCE, "Source")
    with pytest.raises(Conflict, match="Archive the board before"):
        boards.service.delete(ADMIN, SOURCE, "Source")
    boards.service.archive(ADMIN, SOURCE)
    with pytest.raises(ValidationFailure, match="Confirmation name does not match"):
        boards.service.delete(ADMIN, SOURCE, "source")
    boards.service.delete(ADMIN, SOURCE, "  Source ")
    assert SOURCE not in boards.registry.boards
    assert not boards.databases.path(SOURCE).parent.exists()
    assert not backups.exists()
    assert boards.databases.locked_boards == [SOURCE]


def test_deleting_a_board_removes_the_mirror_only_it_linked(boards: Boards) -> None:
    """The board's links go through RepositoryService, so a mirrored repository this was the last
    board of loses its mirror; one another board still links keeps it."""
    other = uuid(2)
    boards.registry.boards[other] = board_row(other, name="Other")
    for repository_id in ("mirror-only", "mirror-shared"):
        boards.registry.code_repositories[repository_id] = repository_row(
            repository_id, provider="git_https", url=f"https://git.example.com/{repository_id}.git"
        )
    files = FakeMirrorFiles()
    files.mirrors = {key: FakeMirror(complete=True) for key in ("mirror-only", "mirror-shared")}
    mirror = MirrorService(
        FakeGit(files, {}), files, hosts=frozenset(), max_bytes=1, timeout_seconds=1
    )
    repositories = RepositoryService(boards.settings, boards.store, mirror=mirror)
    boards.service.repositories = repositories
    repositories.set_board_links(SOURCE, ["mirror-only", "mirror-shared", "repo-a"])
    repositories.set_board_links(other, ["mirror-shared"])
    boards.service.archive(ADMIN, SOURCE)
    boards.service.delete(ADMIN, SOURCE, "Source")
    assert files.removed == ["mirror-only"]
    assert set(boards.registry.repository_links) == {(other, "mirror-shared")}


def test_a_board_whose_files_are_held_is_kept_and_the_leftover_is_named(boards: Boards) -> None:
    boards.service.archive(ADMIN, SOURCE)
    boards.databases.busy.add(SOURCE)
    with pytest.raises(Conflict) as raised:
        boards.service.delete(ADMIN, SOURCE, "Source")
    assert raised.value.code == "board_files_busy"
    assert raised.value.details == {
        "leftover": f"boards/{SOURCE}",
        "backups_leftover": f"backups/{SOURCE}",
        "reason": "PermissionError",
        "errno": 13,
        "winerror": None,
        "platform_profile": boards.settings.file_profile,
    }
    assert SOURCE in boards.registry.boards


# --- export and import ---------------------------------------------------------------------------


def _members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_an_export_holds_the_manifest_a_snapshot_and_the_uploaded_files(boards: Boards) -> None:
    members = _members(boards.service.export_archive(ADMIN, SOURCE))
    assert sorted(members) == ["attachments/a1.bin", "board.sqlite", "manifest.json"]
    manifest = json.loads(members["manifest.json"])
    assert manifest == {
        "format_version": 2,
        "exported_at": NOW,
        "board": {
            "id": SOURCE,
            "name": "Source",
            "description": "The original",
            "created_at": CREATED,
            "updated_at": CREATED,
            "schema_version": 1,
        },
        "attachments": {"files": 1, "bytes": 5},
    }
    assert list(manifest) == ["format_version", "exported_at", "board", "attachments"]
    assert members["board.sqlite"] in boards.databases.images
    assert members["attachments/a1.bin"] == b"first"
    leftovers = sorted(path.name for path in boards.databases.path(SOURCE).parent.iterdir())
    assert leftovers == ["attachments", "board.sqlite"]
    with pytest.raises(Forbidden):
        boards.service.export_archive(READER, SOURCE)


def test_an_import_restores_the_exported_board_under_a_new_id(boards: Boards) -> None:
    data = boards.service.export_archive(ADMIN, SOURCE)
    entry = boards.service.import_archive(ADMIN, data)
    new_id = uuid(1)
    assert (entry["id"], entry["name"], entry["description"], entry["status"]) == (
        new_id,
        "Source",
        "The original",
        "active",
    )
    imported = boards.databases.states[new_id]
    assert set(imported.lists) == {"todo", "done"}
    assert imported.metadata is not None and imported.metadata.id == new_id
    [logged] = imported.activity
    assert (logged.action, json.loads(logged.changes_json)) == (
        "board.imported",
        {"source_format": 2},
    )
    assert (boards.databases.attachments_dir(new_id) / "a1.bin").read_bytes() == b"first"
    assert boards.databases.checked == [new_id]
    assert boards.databases.migrated == [new_id]
    with pytest.raises(Forbidden):
        boards.service.import_archive(WRITER, data)


def _archive(
    manifest: object, *, board: bytes = b"image:1", extra: dict[str, bytes] | None = None
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("board.sqlite", board)
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_an_import_names_an_unnamed_board_and_cuts_long_text(boards: Boards) -> None:
    boards.service.export_archive(ADMIN, SOURCE)
    entry = boards.service.import_archive(ADMIN, _archive({"format_version": 2}))
    assert (entry["name"], entry["description"]) == ("Imported board", "")
    long = {"format_version": 2, "board": {"name": "n" * 300, "description": 7}}
    entry = boards.service.import_archive(ADMIN, _archive(long))
    assert (len(entry["name"]), entry["description"]) == (200, "7")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not a zip", "Import payload is not a valid board archive"),
        (b"", "Import payload is not a valid board archive"),
    ],
)
def test_an_import_refuses_what_is_not_a_zip(boards: Boards, data: bytes, message: str) -> None:
    with pytest.raises(ValidationFailure, match=message):
        boards.service.import_archive(ADMIN, data)


def test_an_import_refuses_an_archive_it_cannot_trust(boards: Boards) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")
    with pytest.raises(ValidationFailure) as raised:
        boards.service.import_archive(ADMIN, buffer.getvalue())
    assert raised.value.details == {"found": ["manifest.json"]}
    with pytest.raises(ValidationFailure, match="Unsupported board archive format"):
        boards.service.import_archive(ADMIN, _archive({"format_version": 1}))
    many = {f"attachments/{index}.bin": b"x" for index in range(1001)}
    with pytest.raises(ValidationFailure, match="more attachments") as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, extra=many))
    assert raised.value.details == {"bytes": 0, "files": 1001}
    declared = {"format_version": 2, "attachments": {"bytes": "209715201"}}
    with pytest.raises(ValidationFailure, match="more attachments"):
        boards.service.import_archive(ADMIN, _archive(declared))
    dots = _archive({"format_version": 2}, extra={"attachments/..": b"x"})
    with pytest.raises(ValidationFailure, match="invalid attachment entry"):
        boards.service.import_archive(ADMIN, dots)
    twice = {"attachments/a.bin": b"x", "attachments/sub/a.bin": b"y"}
    with pytest.raises(ValidationFailure, match="invalid attachment entry") as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, extra=twice))
    assert raised.value.details == {"entry": "attachments/sub/a.bin"}
    assert set(boards.registry.boards) == {SOURCE}


def test_an_import_measures_the_real_attachments_not_the_declared_ones(
    boards: Boards,
) -> None:
    small = boards.settings.model_copy(update={"board_attachment_max_bytes": 4})
    boards.service.settings = small
    extra = {"attachments/a.bin": b"abc", "attachments/b.bin": b"de"}
    with pytest.raises(ValidationFailure, match="more attachments") as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, extra=extra))
    assert raised.value.details == {"bytes": 5, "files": 2}


def test_an_import_refuses_a_member_larger_than_the_limit(boards: Boards) -> None:
    boards.service.settings = boards.settings.model_copy(update={"board_import_max_bytes": 3})
    with pytest.raises(ValidationFailure, match="larger than this installation") as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, board=b"abcd"))
    assert raised.value.details == {"entry": "board.sqlite", "bytes": 4, "max_bytes": 3}


@pytest.mark.parametrize(
    ("manifest", "error"),
    [
        ([], AttributeError),
        ("text", AttributeError),
        ({"format_version": 2, "board": "x"}, AttributeError),
        ({"format_version": 2, "board": None}, AttributeError),
        ({"format_version": 2, "attachments": [1]}, AttributeError),
        ({"format_version": 2, "attachments": {"bytes": [1]}}, TypeError),
    ],
)
def test_a_manifest_of_the_wrong_shape_fails_as_it_always_did(
    boards: Boards, manifest: object, error: type[Exception]
) -> None:
    # The former code read keys with .get and numbers with int(): the same errors, the same 500.
    boards.service.export_archive(ADMIN, SOURCE)
    with pytest.raises(error):
        boards.service.import_archive(ADMIN, _archive(manifest))
    assert set(boards.registry.boards) == {SOURCE}


def test_a_manifest_number_reads_as_int_reads_it(boards: Boards) -> None:
    boards.service.export_archive(ADMIN, SOURCE)
    for value in (True, 3.9, " 12 ", None, 0, ""):
        manifest = {"format_version": 2, "attachments": {"bytes": value}}
        assert boards.service.import_archive(ADMIN, _archive(manifest))["status"] == "active"
    with pytest.raises(ValueError, match="invalid literal"):
        boards.service.import_archive(
            ADMIN, _archive({"format_version": 2, "attachments": {"bytes": "lots"}})
        )


def _left_behind(boards: Boards, board_id: str) -> list[str]:
    """What a board id still has: its row, its directory, its backups directory."""
    return [
        what
        for what, there in (
            ("row", board_id in boards.registry.boards),
            ("files", boards.databases.path(board_id).parent.exists()),
            ("backups", (boards.settings.backups_dir / board_id).exists()),
        )
        if there
    ]


@pytest.mark.parametrize(
    ("reason", "detail"),
    [
        ("integrity_check_failed", "*** in database main ***; Page 7: btreeInitPage() returns 11"),
        ("not_a_board_database", "missing tables: cards, lists"),
        ("unknown_schema_revision", "0099_from_a_newer_release"),
    ],
)
def test_an_archive_whose_database_cannot_become_a_board_is_refused_and_leaves_nothing(
    boards: Boards, reason: ProblemReason, detail: str
) -> None:
    boards.service.export_archive(ADMIN, SOURCE)
    boards.databases.problems[b"image:1"] = DatabaseProblem(reason=reason, detail=detail)
    attached = {"attachments/a.bin": b"x"}
    with pytest.raises(ValidationFailure) as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, extra=attached))
    refusal = raised.value
    assert (refusal.status_code, refusal.code, refusal.message) == (
        422,
        "board_import_invalid",
        IMPORT_REFUSALS[reason],
    )
    assert refusal.details == {"reason": reason, "detail": detail}
    # Judged before it had a row, so nothing could list, recover, migrate or open it.
    assert boards.databases.checked == [uuid(1)]
    assert boards.databases.migrated == []
    assert _left_behind(boards, uuid(1)) == []
    assert uuid(1) not in boards.databases.states


def test_an_archive_whose_database_is_not_a_database_is_refused_with_what_sqlite_said(
    boards: Boards,
) -> None:
    with pytest.raises(ValidationFailure) as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, board=b"garbage"))
    assert (raised.value.code, raised.value.message, raised.value.details) == (
        "board_import_invalid",
        "The archive's board.sqlite is not a database this installation can read",
        {"reason": "not_a_database", "detail": "file is not a database"},
    )
    assert _left_behind(boards, uuid(1)) == []
    assert set(boards.registry.boards) == {SOURCE}


def test_an_archive_that_cannot_be_migrated_is_refused_and_leaves_nothing(boards: Boards) -> None:
    boards.service.export_archive(ADMIN, SOURCE)
    boards.databases.migration_status[uuid(1)] = "failed"
    # The Migration Manager keeps a pre-migration backup of a board it could not upgrade.
    backups = boards.settings.backups_dir / uuid(1)
    backups.mkdir(parents=True)
    (backups / "backup-20261103T100000Z-pre-migration.sqlite").write_bytes(b"image:1")
    with pytest.raises(ValidationFailure) as raised:
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}))
    assert (raised.value.code, raised.value.message, raised.value.details) == (
        "board_import_invalid",
        "Imported board could not be migrated to the current schema",
        {"reason": "migration_failed", "detail": "the backend log names the cause"},
    )
    assert boards.databases.migrated == [uuid(1)]
    assert _left_behind(boards, uuid(1)) == []
    assert set(boards.registry.boards) == {SOURCE}


def test_an_import_that_fails_after_its_row_takes_the_row_and_files_away(boards: Boards) -> None:
    data = boards.service.export_archive(ADMIN, SOURCE)
    # Migrated, then the file cannot be read when the board claims it.
    boards.databases.unreadable.add(uuid(1))
    with pytest.raises(BoardUnreadable):
        boards.service.import_archive(ADMIN, data)
    assert boards.databases.migrated == [uuid(1)]
    assert _left_behind(boards, uuid(1)) == []
    assert set(boards.registry.boards) == {SOURCE}


def test_a_refused_import_whose_files_are_held_keeps_its_row_in_error_and_logs_the_leftover(
    boards: Boards, caplog: pytest.LogCaptureFixture
) -> None:
    boards.service.export_archive(ADMIN, SOURCE)
    boards.databases.migration_status[uuid(1)] = "failed"
    boards.databases.busy.add(uuid(1))
    with (
        caplog.at_level(logging.WARNING, logger="tralala"),
        pytest.raises(ValidationFailure, match="could not be migrated"),
    ):
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}))
    assert boards.registry.boards[uuid(1)].status == "error"
    assert _left_behind(boards, uuid(1)) == ["row", "files"]
    [line] = events(caplog.records)
    assert line == {
        "event": "board_import_leftover",
        "board_id": uuid(1),
        "leftover": f"boards/{uuid(1)}",
        "reason": "PermissionError",
    }


def test_a_refused_import_whose_files_are_held_before_it_had_a_row_adds_none(
    boards: Boards, caplog: pytest.LogCaptureFixture
) -> None:
    boards.databases.busy.add(uuid(1))
    with (
        caplog.at_level(logging.WARNING, logger="tralala"),
        pytest.raises(ValidationFailure, match="not a database"),
    ):
        boards.service.import_archive(ADMIN, _archive({"format_version": 2}, board=b"garbage"))
    assert set(boards.registry.boards) == {SOURCE}
    assert "board_import_leftover" in [line["event"] for line in events(caplog.records)]


def test_an_archive_from_an_older_release_is_migrated_before_it_is_opened(boards: Boards) -> None:
    data = boards.service.export_archive(ADMIN, SOURCE)
    # Opening a board checks its revision, so an older database answers 503 until it is migrated.
    boards.databases.unavailable.add(uuid(1))
    entry = boards.service.import_archive(ADMIN, data)
    assert (entry["id"], entry["status"]) == (uuid(1), "active")
    assert boards.databases.migrated == [uuid(1)]
    assert boards.databases.states[uuid(1)].metadata is not None
    assert boards.databases.states[uuid(1)].activity[0].action == "board.imported"


def test_every_refusal_reason_has_its_own_message() -> None:
    reasons = {
        "not_a_database",
        "integrity_check_failed",
        "not_a_board_database",
        "unknown_schema_revision",
        "migration_failed",
    }
    assert set(IMPORT_REFUSALS) == reasons
    assert len(set(IMPORT_REFUSALS.values())) == len(reasons)


# --- a board whose database cannot be read -------------------------------------------------------


def test_the_list_steps_past_a_board_whose_file_cannot_be_read_and_logs_it_once(
    boards: Boards, caplog: pytest.LogCaptureFixture
) -> None:
    measured = boards.settings.model_copy(update={"board_counts_cache_seconds": 0})
    databases = as_unit_of_work(boards.databases)
    service = BoardService(
        measured,
        boards.store,
        databases,
        as_files(boards.databases),
        migrations=as_migrator(boards.databases),
        schema=BoardSchema(head_revision=HEAD, version=10),
        stats=BoardStatsCache(measured, boards.store, databases, clock=boards.clock),
        agents=AgentService(measured, boards.store),
        repositories=RepositoryService(measured, boards.store),
        clock=boards.clock,
        new_id=Ids(),
    )
    broken = uuid(7)
    boards.registry.boards[broken] = board_row(broken, name="Broken", status="error")
    boards.databases.create_database(broken, "")
    boards.databases.unreadable.add(broken)
    with caplog.at_level(logging.INFO, logger="tralala"):
        first, total = service.list(sort="name", order="asc")
        again, _ = service.list(sort="name", order="asc")
        single = service.get(broken)
    summary = [(e["name"], e["status"], e["loop_count"], e["list_count"]) for e in first]
    assert (summary, total) == ([("Broken", "error", 0, 0), ("Source", "active", 1, 2)], 2)
    assert again == first
    assert single == first[0]
    assert events(caplog.records) == [
        {"event": "board_database_unreadable", "board_id": broken, "skipped": "board_counts"}
    ]
    assert boards.registry.boards[broken].status == "error"


# --- recovery ------------------------------------------------------------------------------------


def test_recovery_activates_an_interrupted_board_with_a_database_and_fails_one_without(
    boards: Boards,
) -> None:
    boards.registry.boards[SOURCE] = boards.registry.boards[SOURCE].__replace__(
        status="maintenance"
    )
    boards.registry.boards[uuid(8)] = board_row(uuid(8), status="maintenance")
    boards.registry.boards[uuid(9)] = board_row(uuid(9), status="error")
    assert boards.service.recover() == [SOURCE, uuid(8)]
    statuses = {board_id: row.status for board_id, row in boards.registry.boards.items()}
    assert statuses == {SOURCE: "active", uuid(8): "error", uuid(9): "error"}
    assert boards.registry.boards[SOURCE].updated_at == NOW

