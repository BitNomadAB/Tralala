"""LoopPlanService on an in-memory board: plan validation, identity reservation, the projection
onto Phases, plan items and dependency edges, publication, and the plan and readiness views.

The service runs its real code inside the board repositories it is handed (the typed fakes in
``tests/unit/fakes``), with a fixed clock and id source; the views are pure functions over typed
rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue, ValidationError

from app.core.context import ActorContext
from app.core.errors import Conflict, NotFound, ValidationFailure
from app.db.generated.board import LoopDependenciesRow, LoopPlanItemsRow, LoopsRow
from app.repositories.loop_plans import PlannedItem
from app.schemas.loops import PlanPayload, PlanPhase, PlanTicket
from app.services.loop_plans import (
    LoopPlanService,
    Prerequisites,
    canonical_phase,
    canonical_ticket,
    dependencies,
    downstream_phase_numbers,
    items_by_phase,
    phase_views,
    plan_hash,
    validate_plan,
)
from app.services.loops_views import board_loop_facts, loop_facts
from app.services.plan_views import PlanViews, Readiness
from app.services.ticket_face import face_view
from app.services.ticket_summaries import summary_basis
from tests.unit.faces import FACE
from tests.unit.fakes.board import (
    BOARD_ID,
    CREATED,
    BoardState,
    FakeBoardRepositories,
    FakeBoardUnitOfWork,
    card_row,
    list_row,
    loop_row,
    phase_row,
    plan_item_row,
    plan_row,
)
from tests.unit.fakes.registry import ConstraintError

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
LOOP = "loop-a"
OTHER = "loop-b"
HUMAN = ActorContext(
    actor_id="actor-1",
    actor_type="user",
    actor_name="Ada",
    scopes=frozenset({"loops:review"}),
    request_id="req-1",
)


def uid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


P1, P2, P3 = uid(1), uid(2), uid(3)
T1, T2, T3, T4, T5 = uid(11), uid(12), uid(13), uid(14), uid(15)


class Ids:
    """new-1, new-2, ... in call order."""

    def __init__(self) -> None:
        self.issued = 0

    def __call__(self) -> str:
        self.issued += 1
        return f"new-{self.issued}"


def service_is_plan_views(plans: LoopPlanService) -> PlanViews:
    """Never called: pyright proves that the service fits the Protocol the other services take."""
    return plans


@dataclass(slots=True)
class World:
    """A board and the plan service with its clock and its id source."""

    state: BoardState
    ids: Ids
    plans: LoopPlanService

    @property
    def repos(self) -> FakeBoardRepositories:
        return FakeBoardRepositories(self.state)


def board(*loops: LoopsRow) -> World:
    """Loop A planning (or ``loops``), each with one column."""
    state = BoardState()
    state.loops = {loop.id: loop for loop in loops or (loop_row(LOOP, stage="planning"),)}
    for loop in state.loops.values():
        state.lists[f"{loop.id}-todo"] = list_row(f"{loop.id}-todo", loop.id, 1024)
    ids = Ids()
    return World(state, ids, LoopPlanService(clock=lambda: NOW, new_id=ids))


def payload(*phases: Mapping[str, object], summary: str = "") -> PlanPayload:
    return PlanPayload.model_validate({"summary": summary, "phases": list(phases)})


def phase(
    phase_id: str, number: int, *tickets: Mapping[str, object], **extra: object
) -> dict[str, object]:
    name = f"Phase {number}"
    return {"id": phase_id, "number": number, "name": name, "tickets": list(tickets), **extra}


def ticket(ticket_id: str, title: str = "", **extra: object) -> dict[str, object]:
    return {"id": ticket_id, "title": title or f"Ticket {ticket_id[-2:]}", **extra}


def refusal(plan: PlanPayload) -> ValidationFailure:
    with pytest.raises(ValidationFailure) as caught:
        validate_plan(plan)
    assert caught.value.code == "invalid_dependency_graph"
    return caught.value


# --- validation ----------------------------------------------------------------------------------


def test_a_plan_with_known_references_and_no_cycle_is_valid() -> None:
    validate_plan(
        payload(
            phase(P1, 1, ticket(T1), ticket(T2, prerequisite_ticket_ids=[T1])),
            phase(P2, 2, ticket(T3, prerequisite_phase_ids=[P1]), prerequisite_phase_ids=[P1]),
        )
    )


@pytest.mark.parametrize(
    ("plan", "message", "details"),
    [
        (
            payload(phase("phase-one", 1, ticket(T1))),
            "Phase ids must be UUIDs so identities survive replanning",
            {"phase_id": "phase-one"},
        ),
        (
            payload(phase(P1, 1, ticket(T1)), phase(P1, 2)),
            "Duplicate phase id",
            {"phase_id": P1},
        ),
        (
            payload(phase(P1, 1, ticket(T1)), phase(P2, 1)),
            "Duplicate phase number",
            {"phase_number": 1},
        ),
        (
            payload(phase(P1, 1, ticket("ticket-one"))),
            "Ticket ids must be UUIDs so identities survive replanning",
            {"ticket_id": "ticket-one"},
        ),
        (
            payload(phase(P1, 1, ticket(T1)), phase(P2, 2, ticket(T1))),
            "Duplicate ticket id",
            {"ticket_id": T1},
        ),
        (
            payload(phase(P1, 1)),
            "A RoadMap must contain at least one planned Ticket",
            None,
        ),
        (
            payload(phase(P1, 1, ticket(T1), prerequisite_phase_ids=[P1])),
            "A Phase cannot depend on itself",
            {"phase_id": P1},
        ),
        (
            payload(phase(P1, 1, ticket(T1), prerequisite_ticket_ids=[P1])),
            "A Phase cannot depend on itself",
            {"phase_id": P1},
        ),
        (
            payload(phase(P1, 1, ticket(T1), prerequisite_phase_ids=[P2])),
            "Phase dependency references an unknown Phase",
            {"phase_id": P1, "missing": P2},
        ),
        (
            payload(phase(P1, 1, ticket(T1), prerequisite_ticket_ids=[T2])),
            "Phase dependency references an unknown Ticket",
            {"phase_id": P1, "missing": T2},
        ),
        (
            payload(phase(P1, 1, ticket(T1, prerequisite_ticket_ids=[T1]))),
            "A Ticket cannot depend on itself",
            {"ticket_id": T1},
        ),
        (
            payload(phase(P1, 1, ticket(T1, prerequisite_phase_ids=[P2]))),
            "Ticket dependency references an unknown Phase",
            {"ticket_id": T1, "missing": P2},
        ),
        (
            payload(phase(P1, 1, ticket(T1, prerequisite_ticket_ids=[T2]))),
            "Ticket dependency references an unknown Ticket",
            {"ticket_id": T1, "missing": T2},
        ),
    ],
)
def test_a_broken_identity_or_reference_is_refused_with_what_is_wrong(
    plan: PlanPayload, message: str, details: dict[str, object] | None
) -> None:
    error = refusal(plan)
    assert error.message == message
    assert error.details == details


@pytest.mark.parametrize(
    ("reason", "instructions"), [(" ", "Do it."), ("Legal", "  "), ("", "")]
)
def test_a_human_only_ticket_needs_a_reason_and_instructions(
    reason: str, instructions: str
) -> None:
    human = ticket(
        T1, required_actor="human", human_action_reason=reason, human_instructions=instructions
    )
    error = refusal(payload(phase(P1, 1, human)))
    assert error.message == "A human-only Ticket needs a reason and instructions"
    assert error.details == {"ticket_id": T1}


def test_a_human_only_ticket_with_a_reason_and_instructions_is_valid() -> None:
    human = ticket(
        T1, required_actor="human", human_action_reason="Legal", human_instructions="Sign it."
    )
    validate_plan(payload(phase(P1, 1, human)))


def test_a_phase_cycle_is_refused_with_the_cycle_it_found() -> None:
    error = refusal(
        payload(
            phase(P1, 1, ticket(T1), prerequisite_phase_ids=[P2]),
            phase(P2, 2, prerequisite_phase_ids=[P1]),
        )
    )
    assert error.message == "Plan dependency graph contains a cycle"
    assert error.details == {"cycle": [f"phase:{P1}", f"phase:{P2}", f"phase:{P1}"]}


def test_an_ordinary_ticket_waits_for_its_own_phase_so_a_phase_waiting_for_it_is_a_cycle() -> None:
    error = refusal(
        payload(
            phase(P1, 1, ticket(T1), prerequisite_ticket_ids=[T2]),
            phase(P2, 2, ticket(T2), prerequisite_phase_ids=[P1]),
        )
    )
    assert error.details == {
        "cycle": [f"phase:{P1}", f"ticket:{T2}", f"phase:{P2}", f"phase:{P1}"]
    }


def test_a_gate_does_not_wait_for_its_phase_so_the_phase_may_wait_for_another_gate() -> None:
    validate_plan(
        payload(
            phase(P1, 1, ticket(T1), prerequisite_ticket_ids=[T2]),
            phase(P2, 2, ticket(T2, execution_mode="pre_phase_gate")),
        )
    )


def test_a_ticket_cycle_through_two_tickets_is_refused() -> None:
    error = refusal(
        payload(
            phase(
                P1,
                1,
                ticket(T1, prerequisite_ticket_ids=[T2]),
                ticket(T2, prerequisite_ticket_ids=[T1]),
            )
        )
    )
    assert error.details == {"cycle": [f"ticket:{T1}", f"ticket:{T2}", f"ticket:{T1}"]}


# --- the canonical plan --------------------------------------------------------------------------


def test_a_canonical_ticket_is_the_model_dump_in_order_followed_by_the_server_fields() -> None:
    model = PlanTicket.model_validate(
        ticket(
            T1,
            "Add columns",
            objective="Why",
            instructions="How",
            required_actor="human",
            execution_mode="pre_phase_gate",
            prerequisite_phase_ids=[P1],
            prerequisite_ticket_ids=[T2],
            acceptance_criteria=["a"],
            expected_evidence=["b"],
            human_action_reason="Legal",
            human_instructions="Sign",
            note="Careful",
            priority="high",
        )
    )
    canonical = canonical_ticket(model, key="K", sequence=3, phase_number=2)
    assert list(canonical) == [*PlanTicket.model_fields, "key", "sequence", "phase_number"]
    assert {**model.model_dump(), "key": "K", "sequence": 3, "phase_number": 2} == canonical


def test_a_canonical_phase_is_the_model_dump_in_order_with_the_canonical_tickets() -> None:
    model = PlanPhase.model_validate(
        phase(
            P1,
            4,
            objective="Store",
            entry_conditions=["in"],
            exit_conditions=["out"],
            prerequisite_phase_ids=[P2],
            prerequisite_ticket_ids=[T2],
            narrative="Story",
        )
    )
    canonical = canonical_phase(model, [])
    assert list(canonical) == list(PlanPhase.model_fields)
    assert model.model_dump() == canonical


def test_the_plan_hash_is_the_sha256_of_the_sorted_compact_json() -> None:
    w = board()
    state = w.state
    draft = w.plans.register_draft(
        w.repos, state.loops[LOOP], payload(phase(P1, 1, ticket(T1))), HUMAN
    )
    text = json.dumps(draft["payload"], sort_keys=True, separators=(",", ":"))
    assert plan_hash(draft["payload"]) == hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- registering a draft -------------------------------------------------------------------------


def register(w: World, plan: PlanPayload, *, loop: str = LOOP) -> str:
    return w.plans.register_draft(w.repos, w.state.loops[loop], plan, HUMAN)["plan_id"]


def test_a_draft_is_stored_with_its_canonical_payload_and_empty_roadmap_revisions() -> None:
    w = board()
    state = w.state
    plan = payload(
        phase(P2, 2, ticket(T3)),
        phase(P1, 1, ticket(T1, "Add columns"), ticket(T2)),
        summary="Two phases",
    )
    draft = w.plans.register_draft(w.repos, state.loops[LOOP], plan, HUMAN)
    stored = state.plans[draft["plan_id"]]
    canonical = draft["payload"]
    assert draft["plan_id"] == "new-1"
    assert draft["revision_number"] == 1
    assert (stored.loop_id, stored.revision_number, stored.status) == (LOOP, 1, "draft")
    assert (stored.roadmap_ai_revision_id, stored.roadmap_revision_id) == ("", "")
    assert (stored.approval_id, stored.activated_at, stored.superseded_at) == (None, None, None)
    assert stored.created_at == STAMP
    assert stored.payload_json == json.dumps(canonical)
    assert stored.content_hash == plan_hash(canonical)
    assert list(canonical) == [
        "schema_version",
        "summary",
        "loop_id",
        "loop_key",
        "plan_id",
        "revision_number",
        "phases",
    ]
    assert canonical["summary"] == "Two phases"
    assert (canonical["loop_id"], canonical["loop_key"], canonical["plan_id"]) == (
        LOOP,
        "L-1",
        "new-1",
    )
    # Phases are stored by number, whatever order the model wrote them in.
    assert [entry["id"] for entry in canonical["phases"]] == [P1, P2]
    assert [
        (entry["key"], entry["sequence"], entry["phase_number"])
        for entry in canonical["phases"][0]["tickets"]
    ] == [("L-1-PH01-001", 1, 1), ("L-1-PH01-002", 2, 1)]
    assert canonical["phases"][1]["tickets"][0]["key"] == "L-1-PH02-001"


def test_ticket_keys_take_the_phase_name_prefix_and_the_loop_key() -> None:
    w = board()
    state = w.state
    named = {"id": P1, "number": 7, "name": "Écoute", "tickets": [ticket(T1)]}
    symbols = {"id": P2, "number": 12, "name": "!!", "tickets": [ticket(T2)]}
    draft = w.plans.register_draft(
        w.repos, state.loops[LOOP], payload(named, symbols), HUMAN
    )
    keys = [entry["tickets"][0]["key"] for entry in draft["payload"]["phases"]]
    assert keys == ["L-1-EC07-001", "L-1-PH12-001"]


def test_revisions_count_per_loop() -> None:
    w = board(loop_row(LOOP, stage="planning"), loop_row(OTHER, stage="planning"))
    state = w.state
    state.loops[OTHER] = state.loops[OTHER].__replace__(key="L-2", sequence=2)
    register(w, payload(phase(P1, 1, ticket(T1))))
    register(w, payload(phase(P1, 1, ticket(T1))))
    register(w, payload(phase(P2, 1, ticket(T2))), loop=OTHER)
    numbers = sorted((plan.loop_id, plan.revision_number) for plan in state.plans.values())
    assert numbers == [(LOOP, 1), (LOOP, 2), (OTHER, 1)]
    stored = [json.loads(plan.payload_json)["revision_number"] for plan in state.plans.values()]
    assert stored == [1, 2, 1]


def test_a_known_ticket_keeps_its_key_and_sequence_and_a_new_one_continues_its_phase() -> None:
    w = board()
    state = w.state
    register(w, payload(phase(P1, 1, ticket(T1), ticket(T2)), phase(P2, 2, ticket(T3))))
    replan = payload(
        phase(P1, 1, ticket(T4), ticket(T1), ticket(T5)),
        phase(P2, 2, ticket(T3), ticket(T2)),
    )
    plans = w.plans
    draft = plans.register_draft(w.repos, state.loops[LOOP], replan, HUMAN)
    first, second = draft["payload"]["phases"]
    # New Tickets continue after the highest sequence the Phase number has, one after another.
    assert [(entry["id"], entry["key"], entry["sequence"]) for entry in first["tickets"]] == [
        (T4, "L-1-PH01-003", 3),
        (T1, "L-1-PH01-001", 1),
        (T5, "L-1-PH01-004", 4),
    ]
    # T2 moves to Phase 2 and keeps its Phase 1 key and sequence.
    assert [(entry["id"], entry["key"], entry["sequence"]) for entry in second["tickets"]] == [
        (T3, "L-1-PH02-001", 1),
        (T2, "L-1-PH01-002", 2),
    ]
    assert second["tickets"][1]["phase_number"] == 2
    assert (state.plan_items[T2].phase_id, state.plan_items[T2].phase_number) == (P2, 2)


def test_an_identity_another_loop_planned_is_not_reused_and_the_store_refuses_it() -> None:
    w = board(loop_row(LOOP, stage="planning"), loop_row(OTHER, stage="planning"))
    state = w.state
    state.loops[OTHER] = state.loops[OTHER].__replace__(key="L-2", sequence=2)
    register(w, payload(phase(P1, 1, ticket(T1))))
    # Only the Loop's own items are known, so T1 is new to the other Loop and its insert breaks
    # the primary key (a 500, as before the conversion).
    with pytest.raises(ConstraintError):
        register(w, payload(phase(P2, 1, ticket(T1))), loop=OTHER)


def test_a_moved_ticket_whose_sequence_is_taken_in_its_new_phase_is_refused_by_the_store() -> None:
    w = board()
    register(w, payload(phase(P1, 1, ticket(T1)), phase(P2, 2, ticket(T2))))
    with pytest.raises(ConstraintError):
        register(w, payload(phase(P2, 2, ticket(T2), ticket(T1))))


def test_a_draft_projects_its_phases_and_items_and_keeps_known_rows_creation() -> None:
    w = board()
    state = w.state
    plan = payload(
        phase(
            P1,
            1,
            ticket(
                T1,
                "Add columns",
                objective="Store",
                instructions="Add them.",
                required_actor="human",
                execution_mode="pre_phase_gate",
                priority="high",
                acceptance_criteria=["exists"],
                expected_evidence=["migration"],
                human_action_reason="Legal",
                human_instructions="Sign",
            ),
            objective="Database",
            entry_conditions=["ready"],
            exit_conditions=["done"],
        )
    )
    first = register(w, plan)
    stored_phase = state.phases[P1]
    assert (stored_phase.loop_id, stored_phase.plan_id, stored_phase.number) == (LOOP, first, 1)
    assert (stored_phase.name, stored_phase.objective) == ("Phase 1", "Database")
    assert (stored_phase.entry_conditions_json, stored_phase.exit_conditions_json) == (
        '["ready"]',
        '["done"]',
    )
    assert (stored_phase.is_qa_phase, stored_phase.created_at) == (0, STAMP)
    item = state.plan_items[T1]
    assert item == LoopPlanItemsRow(
        id=T1,
        loop_id=LOOP,
        plan_id=first,
        phase_id=P1,
        phase_number=1,
        key="L-1-PH01-001",
        ticket_sequence=1,
        title="Add columns",
        objective="Store",
        instructions="Add them.",
        required_actor="human",
        execution_mode="pre_phase_gate",
        priority="high",
        acceptance_criteria_json='["exists"]',
        expected_evidence_json='["migration"]',
        human_action_reason="Legal",
        human_instructions="Sign",
        created_at=STAMP,
        summary="",
        workplace="unknown",
        waiting_for="nothing",
        waiting_reason="",
        face="",
    )
    state.phases[P1] = state.phases[P1].__replace__(created_at=CREATED, is_qa_phase=1)
    state.plan_items[T1] = state.plan_items[T1].__replace__(created_at=CREATED)
    second = register(
        w,
        payload(
            {"id": P1, "number": 3, "name": "Storage", "tickets": [ticket(T1, "Renamed")]}
        ),
    )
    moved = state.phases[P1]
    assert (moved.plan_id, moved.number, moved.name, moved.objective) == (second, 3, "Storage", "")
    assert (moved.entry_conditions_json, moved.created_at, moved.is_qa_phase) == ("[]", CREATED, 1)
    item = state.plan_items[T1]
    assert (item.plan_id, item.phase_number, item.title, item.priority) == (
        second,
        3,
        "Renamed",
        "none",
    )
    assert (item.key, item.ticket_sequence, item.created_at) == ("L-1-PH01-001", 1, CREATED)


def test_rows_a_later_draft_leaves_out_stay_with_their_plan() -> None:
    w = board()
    state = w.state
    first = register(w, payload(phase(P1, 1, ticket(T1)), phase(P2, 2, ticket(T2))))
    second = register(w, payload(phase(P1, 1, ticket(T1))))
    assert (state.phases[P2].plan_id, state.plan_items[T2].plan_id) == (first, first)
    assert (state.phases[P1].plan_id, state.plan_items[T1].plan_id) == (second, second)


def test_a_published_card_follows_its_replanned_item_and_keeps_its_version() -> None:
    w = board()
    state = w.state
    register(w, payload(phase(P1, 1, ticket(T1)), phase(P2, 2, ticket(T2))))
    published = card_row(T1, f"{LOOP}-todo", LOOP, plan_item_id=T1).__replace__(
        priority="low", version=4, ticket_key="L-1-PH01-001"
    )
    unpublished = card_row(T2, f"{LOOP}-todo", LOOP).__replace__(title="Hand-made")
    state.cards = {T1: published, T2: unpublished}
    human = ticket(
        T1,
        "New title",
        instructions="New way",
        required_actor="human",
        execution_mode="pre_phase_gate",
        human_action_reason="Legal",
        human_instructions="Sign",
        priority="urgent",
    )
    register(w, payload(phase(P2, 2, ticket(T2, "Other title")), phase(P3, 3, human)))
    card = state.cards[T1]
    assert (card.title, card.description, card.required_actor, card.execution_mode) == (
        "New title",
        "New way",
        "human",
        "pre_phase_gate",
    )
    assert (card.human_action_reason, card.human_instructions, card.phase_id) == (
        "Legal",
        "Sign",
        P3,
    )
    assert (card.updated_at, card.version, card.priority) == (STAMP, 4, "low")
    # A card that does not carry the item as its plan item is not the item's card.
    assert state.cards[T2] == unpublished


def test_a_new_item_does_not_touch_a_card_with_its_id() -> None:
    w = board()
    state = w.state
    stranger = card_row(T1, f"{LOOP}-todo", LOOP, plan_item_id=T1)
    state.cards = {T1: stranger}
    register(w, payload(phase(P1, 1, ticket(T1, "Planned"))))
    assert state.cards[T1] == stranger


def test_a_published_ticket_carries_the_roadmap_summary_and_a_replan_updates_or_keeps_it() -> None:
    w = board()
    state = w.state
    first = ticket(T1, "First", summary="Adds  the\ncolumns.", instructions="Do it.")
    plan_id = register(w, payload(phase(P1, 1, first, ticket(T2, "Second"))))
    assert state.plan_items[T1].summary == "Adds the columns."
    publish(w, plan_id)
    card = state.cards[T1]
    assert (card.summary, card.summary_source) == ("Adds the columns.", "plan")
    assert card.summary_basis_sha256 == summary_basis("First", "Do it.")
    unsummarised = state.cards[T2]
    assert (unsummarised.summary, unsummarised.summary_source) == ("", "")
    assert unsummarised.summary_basis_sha256 == ""
    # A worker summarised the second Ticket; a replan without a summary for it keeps that one,
    # and a new plan summary replaces the first one's.
    state.cards[T2] = unsummarised.__replace__(
        summary="Written later.", summary_source="agent", summary_basis_sha256="kept"
    )
    renamed = ticket(T1, "First", summary="Adds two columns.", instructions="Do it twice.")
    register(w, payload(phase(P1, 1, renamed, ticket(T2, "Second"))))
    card = state.cards[T1]
    assert (card.summary, card.summary_source) == ("Adds two columns.", "plan")
    assert card.summary_basis_sha256 == summary_basis("First", "Do it twice.")
    kept = state.cards[T2]
    assert (kept.summary, kept.summary_source, kept.summary_basis_sha256) == (
        "Written later.",
        "agent",
        "kept",
    )


def test_the_edges_are_the_newest_drafts_in_order_and_a_repeated_edge_is_kept_once() -> None:
    w = board(loop_row(LOOP, stage="planning"), loop_row(OTHER, stage="planning"))
    state = w.state
    foreign = LoopDependenciesRow(
        id="edge-0",
        loop_id=OTHER,
        plan_id="plan-b",
        source_type="phase",
        source_id="x",
        target_type="phase",
        target_id="y",
        created_at=CREATED,
    )
    state.dependencies = [foreign]
    register(w, payload(phase(P1, 1, ticket(T1), ticket(T2)), phase(P2, 2, ticket(T5))))
    start = w.ids.issued
    plan_id = register(
        w,
        payload(
            phase(P1, 1, ticket(T1), ticket(T2, prerequisite_ticket_ids=[T1])),
            phase(
                P2,
                2,
                ticket(T3, prerequisite_ticket_ids=[T1, T1], prerequisite_phase_ids=[P1]),
                prerequisite_phase_ids=[P1, P1],
                prerequisite_ticket_ids=[T2],
            ),
        ),
    )
    edges = [
        (edge.id, edge.source_type, edge.source_id, edge.target_type, edge.target_id)
        for edge in state.dependencies
    ]
    assert edges[0] == ("edge-0", "phase", "x", "phase", "y")
    # Each edge draws an id, a repeated one too; Phase edges first, then each Ticket's.
    assert plan_id == f"new-{start + 1}"
    assert edges[1:] == [
        (f"new-{start + 2}", "ticket", T2, "ticket", T1),
        (f"new-{start + 3}", "phase", P2, "phase", P1),
        (f"new-{start + 5}", "phase", P2, "ticket", T2),
        (f"new-{start + 6}", "ticket", T3, "ticket", T1),
        (f"new-{start + 8}", "ticket", T3, "phase", P1),
    ]
    assert all(
        (edge.plan_id, edge.created_at) == (plan_id, STAMP) for edge in state.dependencies[1:]
    )
    assert w.ids.issued - start == 9  # plan, six edges, the activity entry


def test_registering_logs_the_plan_and_its_revision() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1))))
    (entry,) = state.activity
    assert (entry.action, entry.entity_type, entry.entity_id) == (
        "loop.plan_registered",
        "loop",
        LOOP,
    )
    assert (entry.actor_id, entry.actor_type, entry.request_id) == ("actor-1", "user", "req-1")
    assert (entry.id, entry.timestamp) == ("new-2", STAMP)
    assert json.loads(entry.changes_json) == {"plan_id": plan_id, "revision": 1}


def test_an_invalid_draft_writes_nothing() -> None:
    w = board()
    state = w.state
    store = FakeBoardUnitOfWork(state)
    plans = w.plans
    with pytest.raises(ValidationFailure), store.writer(BOARD_ID) as repos:
        plans.register_draft(repos, state.loops[LOOP], payload(phase(P1, 1)), HUMAN)
    assert (state.plans, state.phases, state.plan_items, state.activity) == ({}, {}, {}, [])


def test_attaching_revisions_links_both_roadmap_documents() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1))))
    w.plans.attach_revisions(
        w.repos,
        plan_id,
        roadmap_ai_revision_id="doc-ai",
        roadmap_revision_id="doc",
    )
    stored = state.plans[plan_id]
    assert (stored.roadmap_ai_revision_id, stored.roadmap_revision_id) == ("doc-ai", "doc")


# --- publication ---------------------------------------------------------------------------------


def publish(w: World, plan_id: str, *, approval: str | None = "approval-1") -> None:
    w.plans.publish(w.repos, w.state.loops[LOOP], plan_id, HUMAN, approval_id=approval)


def test_an_unknown_plan_is_not_found() -> None:
    with pytest.raises(NotFound) as caught:
        publish(board(), "plan-x")
    assert caught.value.message == "Plan not found"


def test_publishing_needs_an_unarchived_column() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1))))
    state.lists = {
        "gone": list_row("gone", LOOP, 1, archived_at=CREATED),
        "elsewhere": list_row("elsewhere", OTHER, 2),
    }
    with pytest.raises(Conflict) as caught:
        publish(w, plan_id)
    assert (caught.value.code, caught.value.details) == ("loop_required", {"loop_id": LOOP})
    assert caught.value.message == "The Loop has no column to publish Tickets into"


def test_publishing_materialises_every_ticket_in_the_first_column_after_its_cards() -> None:
    w = board()
    state = w.state
    plan_id = register(
        w,
        payload(
            phase(P2, 2, ticket(T3, "Third")),
            phase(
                P1,
                1,
                ticket(
                    T1,
                    "First",
                    instructions="Do it.",
                    priority="high",
                    required_actor="human",
                    execution_mode="pre_phase_gate",
                    human_action_reason="Legal",
                    human_instructions="Sign",
                ),
                ticket(T2, "Second"),
            ),
        ),
    )
    state.lists = {
        "later": list_row("later", LOOP, 2048),
        "b-list": list_row("b-list", LOOP, 1024),
        "a-list": list_row("a-list", LOOP, 1024),
        "archived": list_row("archived", LOOP, 1, archived_at=CREATED),
    }
    # An archived card still holds its position.
    state.cards = {"old": card_row("old", "a-list", LOOP, archived_at=CREATED)}
    state.cards["old"] = state.cards["old"].__replace__(position=5000)
    result = w.plans.publish(
        w.repos, state.loops[LOOP], plan_id, HUMAN, approval_id="approval-1"
    )
    assert result == {
        "plan_id": plan_id,
        "tickets": [
            {"id": T1, "key": "L-1-PH01-001"},
            {"id": T2, "key": "L-1-PH01-002"},
            {"id": T3, "key": "L-1-PH02-001"},
        ],
    }
    first = state.cards[T1]
    assert first == card_row(T1, "a-list", LOOP, plan_item_id=T1).__replace__(
        title="First",
        description="Do it.",
        position=6024,
        priority="high",
        created_at=STAMP,
        updated_at=STAMP,
        phase_id=P1,
        ticket_key="L-1-PH01-001",
        kind="ticket",
        required_actor="human",
        execution_mode="pre_phase_gate",
        human_action_reason="Legal",
        human_instructions="Sign",
        plan_revision_id=plan_id,
    )
    assert [state.cards[card].position for card in (T2, T3)] == [7048, 8072]
    assert state.cards[T3].phase_id == P2


def test_a_card_already_carrying_the_identity_and_key_is_kept() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1), ticket(T2))))
    kept = card_row(T1, f"{LOOP}-todo", LOOP).__replace__(ticket_key="L-1-PH01-001", position=9)
    state.cards = {T1: kept}
    result = w.plans.publish(
        w.repos, state.loops[LOOP], plan_id, HUMAN, approval_id=None
    )
    assert result["tickets"] == [
        {"id": T1, "key": "L-1-PH01-001"},
        {"id": T2, "key": "L-1-PH01-002"},
    ]
    assert state.cards[T1] == kept
    assert state.cards[T2].position == 1033


def test_a_card_with_the_identity_and_another_key_refuses_the_whole_publication() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1), ticket(T2))))
    state.cards = {T2: card_row(T2, f"{LOOP}-todo", LOOP).__replace__(ticket_key="OTHER")}
    before = state.snapshot()
    store = FakeBoardUnitOfWork(state)
    with pytest.raises(Conflict) as caught, store.writer(BOARD_ID) as repos:
        w.plans.publish(repos, state.loops[LOOP], plan_id, HUMAN, approval_id="approval-1")
    assert (caught.value.code, caught.value.details) == (
        "plan_change_required",
        {"ticket_id": T2},
    )
    assert caught.value.message == "A card with this identity already exists with a different key"
    assert (state.cards, state.plans, state.loops) == (before.cards, before.plans, before.loops)


def test_publishing_activates_the_plan_supersedes_the_last_one_and_points_the_loop_at_it() -> None:
    w = board()
    state = w.state
    old = register(w, payload(phase(P1, 1, ticket(T1))))
    publish(w, old, approval="approval-0")
    state.plans[old] = state.plans[old].__replace__(activated_at=CREATED)
    state.loops[LOOP] = state.loops[LOOP].__replace__(version=7, updated_at=CREATED)
    new = register(w, payload(phase(P1, 1, ticket(T1), ticket(T2))))
    publish(w, new, approval="approval-1")
    previous, current = state.plans[old], state.plans[new]
    assert (previous.status, previous.superseded_at, previous.approval_id) == (
        "superseded",
        STAMP,
        "approval-0",
    )
    assert (current.status, current.approval_id, current.activated_at) == (
        "active",
        "approval-1",
        STAMP,
    )
    loop = state.loops[LOOP]
    assert (loop.current_plan_id, loop.updated_at, loop.version) == (new, STAMP, 7)


def test_republishing_an_active_plan_keeps_its_first_activation() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1))))
    publish(w, plan_id)
    state.plans[plan_id] = state.plans[plan_id].__replace__(activated_at=CREATED)
    publish(w, plan_id, approval="approval-2")
    stored = state.plans[plan_id]
    assert (stored.status, stored.activated_at, stored.approval_id) == (
        "active",
        CREATED,
        "approval-2",
    )


def test_publishing_logs_the_plan_and_the_number_of_tickets() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1), ticket(T2))))
    publish(w, plan_id)
    entry = state.activity[-1]
    assert (entry.action, entry.entity_type, entry.entity_id, entry.timestamp) == (
        "loop.plan_published",
        "loop",
        LOOP,
        STAMP,
    )
    assert json.loads(entry.changes_json) == {"plan_id": plan_id, "tickets": 2}


def test_a_stored_payload_that_is_not_a_plan_is_refused_before_anything_is_written() -> None:
    w = board()
    state = w.state
    state.plans["bad"] = plan_row("bad", LOOP, status="draft").__replace__(
        payload_json='{"phases": [{"id": "x"}]}'
    )
    with pytest.raises(ValidationError):
        publish(w, "bad")
    assert (state.cards, state.activity) == ({}, [])


# --- the plan and readiness views ----------------------------------------------------------------


def published(stage: str = "ready") -> World:
    """Loop A at ``stage`` with a published plan: P1 (gate T4, human T2, T1), P2 after P1 with T3
    waiting for T1, and an empty P3 after P2."""
    w = board(loop_row(LOOP, stage=stage))
    plan_id = register(
        w,
        payload(
            phase(
                P1,
                1,
                ticket(T4, "Gate", execution_mode="pre_phase_gate"),
                ticket(T1, "Columns", acceptance_criteria=["exist"]),
                ticket(
                    T2,
                    "Wording",
                    required_actor="human",
                    human_action_reason="Legal",
                    human_instructions="Read",
                ),
                entry_conditions=["db"],
            ),
            phase(
                P2,
                2,
                ticket(T3, "Refuse", prerequisite_ticket_ids=[T1]),
                prerequisite_phase_ids=[P1],
            ),
            phase(P3, 3, prerequisite_phase_ids=[P2]),
        ),
    )
    publish(w, plan_id)
    return w


def complete(state: BoardState, *card_ids: str) -> None:
    for card_id in card_ids:
        state.cards[card_id] = state.cards[card_id].__replace__(completed_at=STAMP)


def readiness_of(w: World) -> Readiness:
    return w.plans.readiness(w.repos, w.state.loops[LOOP])


def test_without_an_active_plan_the_plan_view_is_none() -> None:
    w = board()
    state = w.state
    register(w, payload(phase(P1, 1, ticket(T1))))
    assert w.plans.plan_view(w.repos, state.loops[LOOP]) == {
        "loop_id": LOOP,
        "plan_id": None,
        "revision_number": None,
        "status": "none",
        "activated_at": None,
        "approved_at": None,
        "phases": [],
        "warnings": [],
    }


def test_without_an_active_plan_readiness_asks_for_an_approval() -> None:
    w = board(loop_row(LOOP, stage="roadmap_review"))
    state = w.state
    assert w.plans.readiness(w.repos, state.loops[LOOP]) == {
        "loop_id": LOOP,
        "stage": "roadmap_review",
        "execution_allowed": False,
        "blocked_reason": {
            "code": "approval_required",
            "message": "No approved plan has been published for this Loop",
        },
        "items": [],
        "phases": [],
    }


def test_the_plan_view_shows_the_active_plan_and_its_phases() -> None:
    w = published()
    state = w.state
    plan = next(plan for plan in state.plans.values() if plan.status == "active")
    view = w.plans.plan_view(w.repos, state.loops[LOOP])
    assert (view["plan_id"], view["revision_number"], view["status"]) == (plan.id, 1, "active")
    assert view["activated_at"] == view["approved_at"] == STAMP
    assert view["warnings"] == []
    assert [entry["id"] for entry in view["phases"]] == [P1, P2, P3]
    readiness = w.plans.readiness(w.repos, state.loops[LOOP])
    assert view["phases"] == readiness["phases"]


@pytest.mark.parametrize("stage", ["ready", "in_progress", "awaiting_qa"])
def test_readiness_allows_execution_in_the_delivery_stages(stage: str) -> None:
    view = readiness_of(published(stage))
    assert (view["execution_allowed"], view["blocked_reason"], view["stage"]) == (
        True,
        None,
        stage,
    )


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("replanning", "plan_change_required"),
        ("roadmap_review", "approval_required"),
        ("planning", "approval_required"),
        ("completed", "approval_required"),
    ],
)
def test_readiness_freezes_execution_in_every_other_stage(stage: str, code: str) -> None:
    view = readiness_of(published(stage))
    assert view["execution_allowed"] is False
    assert view["blocked_reason"] == {
        "code": code,
        "message": "Execution transitions are frozen for this Loop stage",
        "stage": stage,
    }


def test_readiness_items_are_the_phase_tickets_in_order() -> None:
    view = readiness_of(published())
    assert [item["id"] for item in view["items"]] == [
        ticket["id"] for phase in view["phases"] for ticket in phase["tickets"]
    ]
    assert [item["id"] for item in view["items"]] == [T4, T1, T2, T3]


def test_a_fresh_plan_waits_for_the_gate_and_every_ticket_names_its_card() -> None:
    w = published()
    state = w.state
    view = w.plans.readiness(w.repos, state.loops[LOOP])
    first, second, third = view["phases"]
    gate_blocker = {
        "type": "ticket",
        "id": T4,
        "key": "L-1-PH01-001",
        "title": "Gate",
        "reason": "pre_phase_gate_incomplete",
    }
    assert (first["state"], first["blocked_by"]) == ("pending", [gate_blocker])
    gate, columns, wording = first["tickets"]
    assert (gate["ready"], gate["blockers"]) == (True, [])
    assert (columns["ready"], columns["blockers"]) == (False, [gate_blocker])
    assert wording["human_action_required"] is True
    assert columns["card_id"] == T1
    assert columns["completed_at"] is None
    assert columns["acceptance_criteria"] == ["exist"]
    assert columns["expected_evidence"] == []
    assert first["entry_conditions"] == ["db"]
    assert first["exit_conditions"] == []
    phase_blocker = {
        "type": "phase",
        "id": P1,
        "reason": "prerequisite_phase_incomplete",
        "phase_number": 1,
        "name": "Phase 1",
    }
    assert (second["state"], second["blocked_by"]) == ("pending", [phase_blocker])
    (refuse,) = second["tickets"]
    assert refuse["blockers"] == [
        {
            "type": "ticket",
            "id": T1,
            "key": "L-1-PH01-002",
            "title": "Columns",
            "reason": "prerequisite_ticket_incomplete",
        },
        phase_blocker,
    ]
    assert refuse["prerequisite_ticket_ids"] == [T1]
    assert second["prerequisite_phase_ids"] == [P1]
    assert (third["state"], third["tickets"]) == ("pending", [])


def test_a_phase_opens_when_its_gate_completes_and_completes_with_its_tickets() -> None:
    w = published()
    state = w.state
    complete(state, T4)
    view = readiness_of(w)
    assert view["phases"][0]["state"] == "active"
    assert [entry["ready"] for entry in view["phases"][0]["tickets"]] == [True, True, True]
    complete(state, T1, T2)
    view = w.plans.readiness(w.repos, state.loops[LOOP])
    assert [entry["state"] for entry in view["phases"]] == ["complete", "active", "pending"]
    assert view["phases"][0]["tickets"][2]["human_action_required"] is False
    assert view["phases"][1]["tickets"][0]["ready"] is True
    complete(state, T3)
    view = w.plans.readiness(w.repos, state.loops[LOOP])
    # An empty Phase is complete once the Phases it waits for are.
    assert [entry["state"] for entry in view["phases"]] == ["complete", "complete", "complete"]


def test_a_gate_ticket_does_not_inherit_its_phases_entry_blockers() -> None:
    w = board(loop_row(LOOP, stage="ready"))
    gate = ticket(T5, "Gate", execution_mode="pre_phase_gate")
    plan_id = register(
        w,
        payload(
            phase(P1, 1, ticket(T1)),
            phase(P2, 2, gate, ticket(T3), prerequisite_phase_ids=[P1]),
        ),
    )
    publish(w, plan_id)
    second = readiness_of(w)["phases"][1]
    assert [blocker["id"] for blocker in second["blocked_by"]] == [P1, T5]
    opening, waiting = second["tickets"]
    assert (opening["ready"], opening["blockers"]) == (True, [])
    assert (waiting["ready"], waiting["blockers"]) == (False, second["blocked_by"])


def test_an_inherited_blocker_the_ticket_already_has_is_listed_once() -> None:
    w = board(loop_row(LOOP, stage="ready"))
    state = w.state
    plan_id = register(
        w,
        payload(
            phase(P1, 1, ticket(T1)),
            phase(
                P2,
                2,
                ticket(T2, prerequisite_ticket_ids=[T1]),
                prerequisite_ticket_ids=[T1],
            ),
        ),
    )
    publish(w, plan_id)
    view = w.plans.readiness(w.repos, state.loops[LOOP])
    (waiting,) = view["phases"][1]["tickets"]
    assert [blocker["id"] for blocker in waiting["blockers"]] == [T1]


def test_downstream_phases_are_every_phase_whose_entry_waits_on_the_ticket() -> None:
    w = board(loop_row(LOOP, stage="ready"))
    plan_id = register(
        w,
        payload(
            phase(P1, 1, ticket(T1), ticket(T4, execution_mode="pre_phase_gate")),
            phase(P2, 2, ticket(T2), prerequisite_ticket_ids=[T1]),
            phase(P3, 3, ticket(T3, prerequisite_ticket_ids=[T2]), prerequisite_phase_ids=[P2]),
        ),
    )
    publish(w, plan_id)
    items = readiness_of(w)["items"]
    downstream = {item["id"]: item["downstream_phase_numbers"] for item in items}
    # P2 waits for T1 and P3 for P2; waiting Tickets and a Phase's own gate are not Phase entries.
    assert downstream == {T1: [2, 3], T4: [], T2: [], T3: []}


def test_the_views_show_the_active_plan_with_what_a_later_draft_took_over() -> None:
    w = published()
    state = w.state
    register(w, payload(phase(P1, 1, ticket(T1, "Renamed")), phase(P2, 2, ticket(T5))))
    view = w.plans.plan_view(w.repos, state.loops[LOOP])
    assert view["revision_number"] == 1
    # The active plan's Phases, with the text the draft gave the rows it took over; the edges are
    # the newest draft's (none).
    assert [entry["id"] for entry in view["phases"]] == [P1, P2, P3]
    assert all(entry["prerequisite_phase_ids"] == [] for entry in view["phases"])
    titles = [entry["title"] for entry in view["phases"][0]["tickets"]]
    assert titles == ["Gate", "Renamed", "Wording"]
    # A Ticket only the draft has is not the active plan's.
    assert [entry["id"] for entry in view["phases"][1]["tickets"]] == [T3]


def test_a_draft_written_from_scratch_stays_out_of_the_plan_until_it_is_published() -> None:
    w = published()
    state = w.state
    p4, p5, t6, t7 = uid(4), uid(5), uid(16), uid(17)
    # A RoadMap written again with new identities: its rows are projected, two Phases numbered 1
    # and 2 beside the active plan's, as on a live board where the views counted both.
    draft = register(w, payload(phase(p4, 1, ticket(t6)), phase(p5, 2, ticket(t7))))
    assert state.phases[p4].plan_id == draft
    view = w.plans.plan_view(w.repos, state.loops[LOOP])
    assert [entry["id"] for entry in view["phases"]] == [P1, P2, P3]
    items = [item["id"] for item in readiness_of(w)["items"]]
    assert t6 not in items and t7 not in items
    facts = loop_facts(w.repos, LOOP).plan
    assert facts is not None and (facts["phase_count"], facts["ticket_total"]) == (3, 4)
    # Published, it is the plan: the first plan's rows stay stored and are no longer read as it.
    publish(w, draft, approval="approval-2")
    view = w.plans.plan_view(w.repos, state.loops[LOOP])
    assert [entry["id"] for entry in view["phases"]] == [p4, p5]
    assert [item["id"] for item in readiness_of(w)["items"]] == [t6, t7]
    board_facts = board_loop_facts(w.repos)[LOOP].plan
    assert board_facts is not None
    assert (board_facts["phase_count"], board_facts["ticket_total"]) == (2, 2)
    assert state.phases[P1].plan_id != draft and P1 in state.phases


def test_a_reference_to_a_row_that_is_gone_still_blocks() -> None:
    plan_phase = phase_row(P1, LOOP, "plan", 1)
    item = plan_item_row(T1, LOOP, "plan", P1)
    edges = dependencies(
        [
            LoopDependenciesRow(
                id="e1",
                loop_id=LOOP,
                plan_id="plan",
                source_type="phase",
                source_id=P1,
                target_type="phase",
                target_id=P3,
                created_at=CREATED,
            ),
            LoopDependenciesRow(
                id="e2",
                loop_id=LOOP,
                plan_id="plan",
                source_type="phase",
                source_id=P1,
                target_type="ticket",
                target_id=T5,
                created_at=CREATED,
            ),
        ]
    )
    grouped = items_by_phase([PlannedItem(item=item, card_id=None, completed_at=None)])
    (view,) = phase_views([plan_phase], grouped, edges)
    assert view["blocked_by"] == [
        {
            "type": "phase",
            "id": P3,
            "reason": "prerequisite_phase_incomplete",
            "phase_number": None,
            "name": "",
        },
        {
            "type": "ticket",
            "id": T5,
            "key": None,
            "title": "",
            "reason": "prerequisite_ticket_incomplete",
        },
    ]


def test_an_item_with_two_cards_counts_each_and_completes_only_with_both() -> None:
    plan_phase = phase_row(P1, LOOP, "plan", 1)
    item = plan_item_row(T1, LOOP, "plan", P1)
    entries = [
        PlannedItem(item=item, card_id="c1", completed_at=STAMP),
        PlannedItem(item=item, card_id="c2", completed_at=None),
    ]
    (view,) = phase_views([plan_phase], items_by_phase(entries), {})
    assert view["state"] == "active"
    assert [entry["card_id"] for entry in view["tickets"]] == ["c1", "c2"]


def test_an_empty_criteria_column_reads_as_no_entries() -> None:
    plan_phase = phase_row(P1, LOOP, "plan", 1).__replace__(entry_conditions_json="")
    item = plan_item_row(T1, LOOP, "plan", P1).__replace__(acceptance_criteria_json="")
    grouped = items_by_phase([PlannedItem(item=item, card_id=None, completed_at=None)])
    (view,) = phase_views([plan_phase], grouped, {})
    assert view["entry_conditions"] == []
    assert view["tickets"][0]["acceptance_criteria"] == []


def test_dependencies_group_each_sources_targets_by_kind_in_order() -> None:
    def edge(n: int, source: str, target_type: str, target: str) -> LoopDependenciesRow:
        return LoopDependenciesRow(
            id=f"e{n}",
            loop_id=LOOP,
            plan_id="plan",
            source_type="ticket",
            source_id=source,
            target_type=target_type,
            target_id=target,
            created_at=CREATED,
        )

    grouped = dependencies(
        [edge(1, T1, "phase", P2), edge(2, T1, "ticket", T3), edge(3, T1, "phase", P1)]
    )
    assert grouped == {f"ticket:{T1}": Prerequisites(phases=[P2, P1], tickets=[T3])}


def test_downstream_numbers_skip_the_node_itself_and_unknown_phases() -> None:
    first = phase_row(P1, LOOP, "plan", 1)
    second = phase_row(P2, LOOP, "plan", 2)
    item = plan_item_row(T1, LOOP, "plan", P1)
    edges: dict[str, Prerequisites] = {
        f"phase:{P2}": Prerequisites(phases=[P1], tickets=[]),
        f"phase:{P1}": Prerequisites(phases=[P3], tickets=[]),
    }
    grouped = items_by_phase([PlannedItem(item=item, card_id=None, completed_at=None)])
    numbers = downstream_phase_numbers([first, second], grouped, edges)
    assert numbers[f"phase:{P1}"] == {2}
    assert numbers[f"phase:{P2}"] == set()
    assert numbers[f"ticket:{T1}"] == set()


def test_a_phase_is_judged_after_the_phases_it_waits_for_whatever_its_number() -> None:
    p4 = uid(4)
    w = board(loop_row(LOOP, stage="ready"))
    plan_id = register(
        w,
        payload(
            phase(P1, 1, prerequisite_phase_ids=[P2]),
            phase(P2, 2, ticket(T1)),
            phase(P3, 3, ticket(T3), prerequisite_phase_ids=[P1]),
            phase(p4, 4, prerequisite_phase_ids=[P1, P3]),
        ),
    )
    publish(w, plan_id)
    complete(w.state, T1)
    view = readiness_of(w)
    # The empty Phase 1 is complete once Phase 2 is, so Phase 3 may start; the empty Phase 4
    # waits for every Phase it names.
    assert [entry["state"] for entry in view["phases"]] == [
        "complete",
        "complete",
        "active",
        "pending",
    ]
    assert view["phases"][2]["blocked_by"] == []
    assert [blocker["id"] for blocker in view["phases"][3]["blocked_by"]] == [P3]


def test_a_gate_does_not_carry_its_phases_dependents_downstream() -> None:
    p4 = uid(4)
    w = board(loop_row(LOOP, stage="ready"))
    plan_id = register(
        w,
        payload(
            phase(P1, 1, ticket(T1)),
            phase(
                P2,
                2,
                ticket(T2, execution_mode="pre_phase_gate"),
                ticket(T3),
                prerequisite_ticket_ids=[T1],
            ),
            phase(P3, 3, ticket(T4), prerequisite_ticket_ids=[T3]),
            phase(p4, 4, ticket(T5), prerequisite_ticket_ids=[T2]),
        ),
    )
    publish(w, plan_id)
    downstream = {item["id"]: item["downstream_phase_numbers"] for item in readiness_of(w)["items"]}
    # T1 opens Phase 2, whose ordinary T3 opens Phase 3; Phase 4 waits only for the gate T2.
    assert downstream[T1] == [2, 3]
    assert downstream[T2] == [4]


# --- the face for people -------------------------------------------------------------------------

FACE_FIELDS_OF = ("why", "if_skipped", "pros", "cons", "steps")


def stored(face: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The face fields of ``face`` as the column's JSON object holds them."""
    return {name: face[name] for name in FACE_FIELDS_OF}


def test_publishing_copies_each_items_face_to_its_card_and_a_replan_updates_or_keeps_it() -> None:
    w = board()
    state = w.state
    first = ticket(T1, "First", **FACE)
    plan_id = register(w, payload(phase(P1, 1, first, ticket(T2, "Second"))))
    assert json.loads(state.plan_items[T1].face) == stored(FACE)
    assert state.plan_items[T2].face == ""
    publish(w, plan_id)
    assert state.cards[T1].face == state.plan_items[T1].face
    assert state.cards[T2].face == ""
    assert face_view(state.cards[T1].summary, state.cards[T1].face) == {
        "summary": FACE["summary"],
        **stored(FACE),
    }
    # A new RoadMap revision with another face replaces it; one without a face keeps the card's.
    changed: dict[str, JsonValue] = {**FACE, "steps": ["Show one sign-in form"]}
    register(w, payload(phase(P1, 1, ticket(T1, "First", **changed), ticket(T2, "Second"))))
    assert json.loads(state.cards[T1].face) == stored(changed)
    register(w, payload(phase(P1, 1, ticket(T1, "First"), ticket(T2, "Second"))))
    assert json.loads(state.cards[T1].face) == stored(changed)


def test_a_plan_stored_before_the_face_still_publishes_its_tickets_without_one() -> None:
    w = board()
    state = w.state
    plan_id = register(w, payload(phase(P1, 1, ticket(T1, "First", **FACE))))
    stored = json.loads(state.plans[plan_id].payload_json)
    for entry in stored["phases"][0]["tickets"]:
        for name in FACE_FIELDS_OF:
            del entry[name]
    state.plans[plan_id] = state.plans[plan_id].__replace__(payload_json=json.dumps(stored))
    publish(w, plan_id)
    card = state.cards[T1]
    assert (card.ticket_key, card.face, card.summary) == ("L-1-PH01-001", "", FACE["summary"])
    assert face_view(card.summary, card.face) is None
