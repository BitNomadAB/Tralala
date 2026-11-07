"""A Loop's QA cycle and its Task.

One active cycle per Loop, the Verification Phase its Task belongs to, the delivery baseline the
cycle was opened against, the activity a QA step writes, and a cycle as an API entry. The
functions take the id source and the clock as arguments; ``LoopQaService`` hands over its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict

from ..core.context import ActorContext
from ..core.errors import Conflict
from ..db.generated.board import CardsRow, LoopPhasesRow, LoopQaCyclesRow, LoopsRow
from ..repositories.board import BoardRepositories
from .activity import activity_entry
from .loop_identifiers import format_ticket_key
from .loops import QA_OPEN_STATUSES

QA_PHASE_NAME = "Verification"
# The instruction and attestation columns are answered parsed, under names without ``_json``.
_JSON_COLUMNS = ("ai_instructions_json", "human_instructions_json", "attestation_json")

type Entry = dict[str, object]


def _json_object(raw: str) -> object:
    return json.loads(raw or "{}")


def active_cycle(cycles: list[LoopQaCyclesRow]) -> LoopQaCyclesRow | None:
    return next((cycle for cycle in cycles if cycle.status in QA_OPEN_STATUSES), None)


def cycle_by_id(cycles: list[LoopQaCyclesRow], cycle_id: str) -> LoopQaCyclesRow | None:
    return next((cycle for cycle in cycles if cycle.id == cycle_id), None)


def log_loop_activity(
    repos: BoardRepositories,
    actor: ActorContext,
    action: str,
    loop_id: str,
    changes: Mapping[str, object],
    now: str,
    *,
    new_id: Callable[[], str],
) -> None:
    repos.activity.add(
        activity_entry(
            actor,
            action=action,
            entity_type="loop",
            entity_id=loop_id,
            changes=changes,
            entry_id=new_id(),
            timestamp=now,
        )
    )


def _qa_phase(
    repos: BoardRepositories,
    loop_id: str,
    *,
    new_id: Callable[[], str],
    timestamp: Callable[[], str],
) -> LoopPhasesRow:
    phases = repos.phases.for_loop(loop_id)
    existing = next((phase for phase in phases if phase.is_qa_phase == 1), None)
    if existing is not None:
        return existing
    plan = repos.plans.active(loop_id)
    if plan is None:
        raise Conflict(
            "A QA Task needs an approved plan before implementation can be accepted",
            code="approval_required",
        )
    phase = LoopPhasesRow(
        id=new_id(),
        loop_id=loop_id,
        plan_id=plan.id,
        number=max((other.number for other in phases), default=0) + 1,
        name=QA_PHASE_NAME,
        objective="Verify the delivered work against the approved requirements.",
        entry_conditions_json="[]",
        exit_conditions_json="[]",
        is_qa_phase=1,
        created_at=timestamp(),
    )
    repos.phases.add(phase)
    return phase


def ensure_qa_cycle(
    repos: BoardRepositories,
    loop: LoopsRow,
    actor: ActorContext,
    *,
    new_id: Callable[[], str],
    timestamp: Callable[[], str],
) -> LoopQaCyclesRow:
    """One active QA cycle per Loop; repeated attempts reuse it."""
    cycles = repos.qa.cycles(loop.id)
    active = active_cycle(cycles)
    if active is not None:
        return active
    number = max((cycle.cycle_number for cycle in cycles), default=0) + 1
    phase = _qa_phase(repos, loop.id, new_id=new_id, timestamp=timestamp)
    columns = repos.lists.for_loop(loop.id, include_archived=False)
    if not columns:
        raise Conflict("The Loop has no column for its QA Task", code="loop_required")
    cycle_id = new_id()
    card_id = new_id()
    key = format_ticket_key(loop.key, "QA", phase.number, number)
    now = timestamp()
    repos.cards.add(
        CardsRow(
            id=card_id,
            list_id=columns[0].id,
            title=f"QA — {loop.name}",
            description=(
                "QA is outstanding. Instructions are generated from the approved plan and "
                "the recorded delivery results."
            ),
            position=repos.cards.highest_position(columns[0].id) + 1024,
            priority="none",
            due_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
            archived_at=None,
            version=1,
            assignee_actor_id=None,
            assignee_type=None,
            assignee_name=None,
            assigned_at=None,
            assigned_by_actor_id=None,
            loop_id=loop.id,
            phase_id=phase.id,
            plan_item_id=None,
            ticket_key=key,
            kind="qa",
            required_actor="human",
            execution_mode="normal",
            human_action_reason="",
            human_instructions="",
            human_confirmed_at=None,
            human_confirmed_by_actor_id=None,
            plan_revision_id=loop.current_plan_id,
            summary="",
            summary_source="",
            summary_basis_sha256="",
            workplace="unknown",
            waiting_for="nothing",
            waiting_reason="",
            waiting_set_at=None,
            waiting_set_by=None,
        )
    )
    cycle = LoopQaCyclesRow(
        id=cycle_id,
        loop_id=loop.id,
        cycle_number=number,
        status="pending",
        card_id=card_id,
        ai_instructions_json="{}",
        human_instructions_json="{}",
        instruction_revision=0,
        delivery_baseline=delivery_baseline(repos, loop.id),
        generation_run_id=None,
        attestation_json="{}",
        created_at=now,
        updated_at=now,
        decided_at=None,
        decided_by_actor_id=None,
        decision_note="",
    )
    repos.qa.add(cycle)
    repos.loops.set_active_qa_cycle(loop.id, cycle_id, now=now)
    log_loop_activity(
        repos,
        actor,
        "loop.qa_cycle_created",
        loop.id,
        {"cycle": number, "card_id": card_id, "key": key},
        now,
        new_id=new_id,
    )
    return cycle


def delivery_tickets(repos: BoardRepositories, loop_id: str) -> list[CardsRow]:
    return [card for card in repos.archive.tickets(loop_id) if card.kind == "ticket"]


def delivery_baseline(repos: BoardRepositories, loop_id: str) -> str:
    records = [
        {"ticket_key": card.ticket_key, "completed_at": card.completed_at}
        for card in delivery_tickets(repos, loop_id)
    ]
    return json.dumps(records, sort_keys=True)


def serialize_cycle(repos: BoardRepositories, cycle: LoopQaCyclesRow) -> Entry:
    entry: Entry = {
        name: value for name, value in asdict(cycle).items() if name not in _JSON_COLUMNS
    }
    entry["ai_instructions"] = _json_object(cycle.ai_instructions_json)
    entry["human_instructions"] = _json_object(cycle.human_instructions_json)
    entry["attestation"] = _json_object(cycle.attestation_json)
    entry["results"] = [asdict(result) for result in repos.qa.results(cycle.id)]
    return entry
