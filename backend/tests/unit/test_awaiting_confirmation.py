"""A Ticket held up only by a person's confirmation: readiness marks it ``awaiting_confirmation``
with the human-only Tickets behind it, its state is ready, and real ordering still blocks."""

from __future__ import annotations

from app.db.generated.board import LoopDependenciesRow, LoopPhasesRow
from app.repositories.loop_plans import PlannedItem
from app.services.loop_plans import (
    confirmations_behind,
    dependencies,
    items_by_phase,
    phase_views,
)
from app.services.plan_views import Blocker, Confirmation, ReadinessItem, plan_blocks
from tests.unit.fakes.board import CREATED, phase_row, plan_item_row

LOOP = "loop-a"
STAMP = "2026-11-03T10:00:00Z"
P1, P2, P3 = "phase-1", "phase-2", "phase-3"


def phase(phase_id: str, number: int) -> LoopPhasesRow:
    return phase_row(phase_id, LOOP, "plan", number)


def item(
    item_id: str,
    phase_id: str,
    *,
    human: bool = False,
    done: bool = False,
    gate: bool = False,
) -> PlannedItem:
    row = plan_item_row(item_id, LOOP, "plan", phase_id).__replace__(
        required_actor="human" if human else "any",
        execution_mode="pre_phase_gate" if gate else "normal",
    )
    return PlannedItem(item=row, card_id=f"card-{item_id}", completed_at=STAMP if done else None)


def edge(source_type: str, source: str, target_type: str, target: str) -> LoopDependenciesRow:
    return LoopDependenciesRow(
        id=f"{source}-{target}",
        loop_id=LOOP,
        plan_id="plan",
        source_type=source_type,
        source_id=source,
        target_type=target_type,
        target_id=target,
        created_at=CREATED,
    )


def readiness(
    phases: list[LoopPhasesRow], entries: list[PlannedItem], edges: list[LoopDependenciesRow]
) -> dict[str, ReadinessItem]:
    views = phase_views(phases, items_by_phase(entries), dependencies(edges), loop_closed=False)
    return {ticket["id"]: ticket for view in views for ticket in view["tickets"]}


def confirmation(item_id: str) -> Confirmation:
    return {"id": item_id, "key": f"K-{item_id}", "title": f"Item {item_id}"}


def test_a_ticket_behind_an_unconfirmed_person_s_ticket_is_ready_and_awaits_its_confirmation() -> (
    None
):
    tickets = readiness(
        [phase(P1, 1)],
        [item("h", P1, human=True), item("t", P1)],
        [edge("ticket", "t", "ticket", "h")],
    )
    held = tickets["t"]
    assert (held["ready"], held["awaiting_confirmation"]) == (False, True)
    assert held["confirmations"] == [confirmation("h")]
    assert [blocker["id"] for blocker in held["blockers"]] == ["h"]
    assert held["state"] == "ready"
    assert not plan_blocks(held)
    # The person's Ticket itself is held up by nothing.
    assert (tickets["h"]["awaiting_confirmation"], tickets["h"]["confirmations"]) == (False, [])
    assert tickets["h"]["state"] == "ready"


def test_once_completed_it_keeps_the_mark_until_the_person_confirms() -> None:
    phases = [phase(P1, 1), phase(P2, 2)]
    edges = [edge("phase", P2, "phase", P1)]
    before = readiness(phases, [item("h", P1, human=True), item("t", P2, done=True)], edges)
    assert before["t"]["state"] is None
    assert (before["t"]["awaiting_confirmation"], before["t"]["confirmations"]) == (
        True,
        [confirmation("h")],
    )
    after = readiness(
        phases, [item("h", P1, human=True, done=True), item("t", P2, done=True)], edges
    )
    assert (after["t"]["ready"], after["t"]["awaiting_confirmation"]) == (True, False)
    assert after["t"]["confirmations"] == []


def test_a_phase_behind_a_phase_is_followed_to_the_person_s_ticket() -> None:
    # Phase 3 waits for Phase 2, which has no Tickets and waits for Phase 1 with the person's task.
    tickets = readiness(
        [phase(P1, 1), phase(P2, 2), phase(P3, 3)],
        [item("h", P1, human=True), item("done", P1, done=True), item("t", P3)],
        [edge("phase", P2, "phase", P1), edge("phase", P3, "phase", P2)],
    )
    assert [blocker["id"] for blocker in tickets["t"]["blockers"]] == [P2]
    assert tickets["t"]["confirmations"] == [confirmation("h")]
    assert tickets["t"]["state"] == "ready"


def test_a_person_s_ticket_behind_unfinished_work_is_followed_and_blocks() -> None:
    # Phase 3 waits for Phase 2, whose only open Ticket is a person's task that itself waits for
    # Phase 1, where ordinary work is unfinished: that is real ordering all the way.
    tickets = readiness(
        [phase(P1, 1), phase(P2, 2), phase(P3, 3)],
        [item("work", P1), item("h", P2, human=True), item("t", P3)],
        [edge("phase", P2, "phase", P1), edge("phase", P3, "phase", P2)],
    )
    assert (tickets["t"]["awaiting_confirmation"], tickets["t"]["state"]) == (False, "blocked")
    assert tickets["h"]["state"] == "blocked"
    assert plan_blocks(tickets["t"])


def test_one_unfinished_ordinary_ticket_among_them_blocks() -> None:
    tickets = readiness(
        [phase(P1, 1), phase(P2, 2)],
        [item("h", P1, human=True), item("work", P1), item("t", P2)],
        [edge("phase", P2, "phase", P1)],
    )
    assert (tickets["t"]["awaiting_confirmation"], tickets["t"]["confirmations"]) == (False, [])
    assert tickets["t"]["state"] == "blocked"


def test_two_person_s_tickets_and_a_gate_are_all_named_once() -> None:
    # The Ticket waits for Phase 1 (two person's tasks) and for its own Phase's gate, a person's
    # task too; the gate waits for nothing.
    tickets = readiness(
        [phase(P1, 1), phase(P2, 2)],
        [
            item("h1", P1, human=True),
            item("h2", P1, human=True),
            item("gate", P2, human=True, gate=True),
            item("t", P2),
        ],
        [edge("phase", P2, "phase", P1), edge("ticket", "t", "ticket", "h1")],
    )
    # In the order they are met: its own prerequisite, its own Phase's gate, then the Phase before.
    assert tickets["t"]["confirmations"] == [
        confirmation("h1"),
        confirmation("gate"),
        confirmation("h2"),
    ]
    assert tickets["t"]["state"] == "ready"


def test_a_person_s_ticket_behind_another_person_s_ticket_awaits_it() -> None:
    tickets = readiness(
        [phase(P1, 1)],
        [item("first", P1, human=True), item("second", P1, human=True)],
        [edge("ticket", "second", "ticket", "first")],
    )
    second = tickets["second"]
    assert (second["awaiting_confirmation"], second["confirmations"]) == (
        True,
        [confirmation("first")],
    )
    assert (second["state"], second["human_action_required"]) == ("ready", True)


def test_a_wait_still_wins_over_the_mark() -> None:
    entries = [item("h", P1, human=True), item("t", P1)]
    entries[1] = PlannedItem(
        item=entries[1].item,
        card_id="card-t",
        completed_at=None,
        waiting_for="decision",
    )
    tickets = readiness([phase(P1, 1)], entries, [edge("ticket", "t", "ticket", "h")])
    assert (tickets["t"]["awaiting_confirmation"], tickets["t"]["state"]) == (True, "needs_input")


def test_confirmations_behind_is_empty_for_no_blocker_an_unknown_one_and_real_work() -> None:
    human: dict[str, Confirmation] = {"h": confirmation("h")}
    on_human: Blocker = {"type": "ticket", "id": "h", "reason": "prerequisite_ticket_incomplete"}
    on_work: Blocker = {"type": "ticket", "id": "w", "reason": "prerequisite_ticket_incomplete"}
    gone: Blocker = {"type": "phase", "id": "gone", "reason": "prerequisite_phase_incomplete"}

    def behind(blockers: list[Blocker]) -> list[Confirmation]:
        return confirmations_behind(
            blockers, phase_holds={}, item_holds={}, open_human=human
        )

    assert behind([]) == []
    assert behind([on_human]) == [confirmation("h")]
    assert behind([on_human, on_work]) == []
    assert behind([gone]) == []
    # A cycle (validation refuses one) ends instead of running on.
    looped = confirmations_behind(
        [on_human], phase_holds={}, item_holds={"h": [on_human]}, open_human=human
    )
    assert looped == [confirmation("h")]
