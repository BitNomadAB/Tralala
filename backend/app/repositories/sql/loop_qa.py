"""``LoopQaRepository`` over SQLAlchemy."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import (
    LOOP_QA_CYCLES_COLUMNS,
    LOOP_QA_RESULTS_COLUMNS,
    LoopQaCyclesRow,
    LoopQaResultsRow,
)

_CYCLES_COLUMNS = sql.column_list(LOOP_QA_CYCLES_COLUMNS)
_CYCLES = text(
    f"SELECT {_CYCLES_COLUMNS} FROM loop_qa_cycles"  # noqa: S608 - from LOOP_QA_CYCLES_COLUMNS
    " WHERE loop_id = :id ORDER BY cycle_number"
)
_ALL_CYCLES = text(
    f"SELECT {_CYCLES_COLUMNS} FROM loop_qa_cycles"  # noqa: S608 - from LOOP_QA_CYCLES_COLUMNS
    " WHERE loop_id IN (SELECT id FROM loops) ORDER BY cycle_number"
)
_SUPERSEDE_OPEN = text(
    "UPDATE loop_qa_cycles SET status = 'superseded', updated_at = :now"
    " WHERE loop_id = :id AND status IN ('pending','instructions_ready','in_progress')"
)

_ADD = text(
    "INSERT INTO loop_qa_cycles (id, loop_id, cycle_number, status, card_id, ai_instructions_json,"
    " human_instructions_json, instruction_revision, delivery_baseline, generation_run_id,"
    " attestation_json, created_at, updated_at, decided_at, decided_by_actor_id, decision_note)"
    " VALUES (:id, :loop_id, :cycle_number, :status, :card_id, :ai_instructions_json,"
    " :human_instructions_json, :instruction_revision, :delivery_baseline, :generation_run_id,"
    " :attestation_json, :created_at, :updated_at, :decided_at, :decided_by_actor_id,"
    " :decision_note)"
)
_SET_INSTRUCTIONS = text(
    "UPDATE loop_qa_cycles SET status = 'instructions_ready', ai_instructions_json = :ai,"
    " human_instructions_json = :human, instruction_revision = :revision,"
    " generation_run_id = :run_id, delivery_baseline = :baseline, updated_at = :now"
    " WHERE id = :id"
)
_IN_PROGRESS = text(
    "UPDATE loop_qa_cycles SET status = 'in_progress', updated_at = :now WHERE id = :id"
)
_DECIDE = text(
    "UPDATE loop_qa_cycles SET status = :status, decided_at = :now, decided_by_actor_id = :actor,"
    " decision_note = :note, updated_at = :now WHERE id = :id"
)
_RESULTS = text(
    f"SELECT {sql.column_list(LOOP_QA_RESULTS_COLUMNS)} FROM loop_qa_results"  # noqa: S608 - generated
    " WHERE cycle_id = :id ORDER BY created_at, rowid"
)
_ADD_RESULT = text(
    "INSERT INTO loop_qa_results (id, cycle_id, scenario_id, status, reason, evidence, actor_id,"
    " actor_type, actor_name, tested_baseline, instruction_revision,"
    " disposition_approved_by_actor_id, disposition_note, created_at) VALUES (:id, :cycle_id,"
    " :scenario_id, :status, :reason, :evidence, :actor_id, :actor_type, :actor_name,"
    " :tested_baseline, :instruction_revision, :disposition_approved_by_actor_id,"
    " :disposition_note, :created_at)"
)
_APPROVE_NOT_APPLICABLE = text(
    "UPDATE loop_qa_results SET disposition_approved_by_actor_id = :actor, disposition_note = :note"
    " WHERE cycle_id = :cycle AND scenario_id = :sid AND status = 'not_applicable'"
)


class SqlLoopQaRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def cycles(self, loop_id: str | None) -> list[LoopQaCyclesRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_CYCLES)
        else:
            result = self._connection.execute(_CYCLES, {"id": loop_id})
        return [LoopQaCyclesRow.from_mapping(row) for row in result.mappings()]

    def supersede_open(self, loop_id: str, *, now: str) -> None:
        self._connection.execute(_SUPERSEDE_OPEN, {"now": now, "id": loop_id})

    def add(self, row: LoopQaCyclesRow) -> None:
        self._connection.execute(_ADD, asdict(row))

    def set_instructions(
        self,
        cycle_id: str,
        *,
        ai_json: str,
        human_json: str,
        revision: int,
        run_id: str,
        baseline: str,
        now: str,
    ) -> None:
        self._connection.execute(
            _SET_INSTRUCTIONS,
            {
                "ai": ai_json,
                "human": human_json,
                "revision": revision,
                "run_id": run_id,
                "baseline": baseline,
                "now": now,
                "id": cycle_id,
            },
        )

    def mark_in_progress(self, cycle_id: str, *, now: str) -> None:
        self._connection.execute(_IN_PROGRESS, {"now": now, "id": cycle_id})

    def decide(self, cycle_id: str, *, status: str, actor_id: str, note: str, now: str) -> None:
        parameters = {"status": status, "now": now, "actor": actor_id, "note": note, "id": cycle_id}
        self._connection.execute(_DECIDE, parameters)

    def results(self, cycle_id: str) -> list[LoopQaResultsRow]:
        result = self._connection.execute(_RESULTS, {"id": cycle_id}).mappings()
        return [LoopQaResultsRow.from_mapping(row) for row in result]

    def add_result(self, row: LoopQaResultsRow) -> None:
        self._connection.execute(_ADD_RESULT, asdict(row))

    def approve_not_applicable(
        self, cycle_id: str, scenario_id: str, *, actor_id: str, note: str
    ) -> None:
        parameters = {"actor": actor_id, "note": note, "cycle": cycle_id, "sid": scenario_id}
        self._connection.execute(_APPROVE_NOT_APPLICABLE, parameters)
