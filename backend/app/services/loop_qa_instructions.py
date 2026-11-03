"""A QA cycle's scenario set.

Storing generated or submitted instructions in both views on the cycle and its Task, reading them
back, and what still blocks accepting the cycle against them. The functions take the id source
and the clock as arguments; ``LoopQaService`` hands over its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..db.generated.board import LoopQaCyclesRow, LoopsRow
from ..repositories.board import BoardRepositories
from ..schemas.loops import QaInstructions
from .loop_qa_cycles import Entry, delivery_baseline, ensure_qa_cycle
from .loop_qa_render import render_qa_ai, render_qa_human, render_qa_task

BLOCKING_RESULT_STATUSES = {"failed", "blocked", "not_run"}


def apply_qa_instructions(
    repos: BoardRepositories,
    loop: LoopsRow,
    instructions: QaInstructions,
    *,
    run_id: str,
    provenance: Mapping[str, object],
    new_id: Callable[[], str],
    timestamp: Callable[[], str],
) -> Entry:
    actor = ActorContext(
        actor_id=str(provenance.get("agent_id") or "generation"),
        actor_type="agent",
        actor_name=str(provenance.get("agent_name") or "QA agent"),
    )
    cycle = ensure_qa_cycle(repos, loop, actor, new_id=new_id, timestamp=timestamp)
    revision = cycle.instruction_revision + 1
    now = timestamp()
    ai_view = {
        "markdown": render_qa_ai(instructions),
        "scenarios": [scenario.model_dump() for scenario in instructions.scenarios],
        "provenance": dict(provenance),
    }
    human_view = {
        "markdown": render_qa_human(instructions),
        "scenarios": [scenario.model_dump() for scenario in instructions.scenarios],
    }
    repos.qa.set_instructions(
        cycle.id,
        ai_json=json.dumps(ai_view),
        human_json=json.dumps(human_view),
        revision=revision,
        run_id=run_id,
        baseline=delivery_baseline(repos, loop.id),
        now=now,
    )
    card = None if cycle.card_id is None else repos.cards.get(cycle.card_id)
    if card is not None:
        repos.cards.update(
            card.id,
            {
                "description": render_qa_task(instructions, cycle.cycle_number),
                "updated_at": now,
                "version": card.version + 1,
            },
        )
    return {
        "cycle_id": cycle.id,
        "instruction_revision": revision,
        "card_id": cycle.card_id,
    }


def read_qa_instructions(cycle: LoopQaCyclesRow) -> QaInstructions | None:
    payload = json.loads(cycle.ai_instructions_json or "{}")
    scenarios = payload.get("scenarios")
    if not scenarios:
        return None
    return QaInstructions.model_validate(
        {"schema_version": 1, "summary": "", "scenarios": scenarios}
    )


def qa_acceptance_blockers(
    repos: BoardRepositories,
    cycle: LoopQaCyclesRow,
    approved_not_applicable: list[str],
) -> list[dict[str, str | None]]:
    instructions = read_qa_instructions(cycle)
    if instructions is None:
        return [{"scenario_id": None, "reason": "instructions_missing"}]
    latest = {record.scenario_id: record for record in repos.qa.results(cycle.id)}
    blockers: list[dict[str, str | None]] = []
    for scenario in instructions.scenarios:
        result = latest.get(scenario.id)
        if result is None:
            blockers.append({"scenario_id": scenario.id, "reason": "not_run"})
            continue
        if result.status == "not_applicable":
            if scenario.id not in approved_not_applicable:
                blockers.append(
                    {
                        "scenario_id": scenario.id,
                        "reason": "not_applicable_requires_human_approval",
                    }
                )
            continue
        if result.status in BLOCKING_RESULT_STATUSES:
            blockers.append(
                {
                    "scenario_id": scenario.id,
                    "reason": result.status,
                    "detail": result.reason,
                }
            )
        if result.instruction_revision != cycle.instruction_revision:
            blockers.append({"scenario_id": scenario.id, "reason": "instructions_revised"})
    return blockers
