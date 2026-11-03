"""``GenerationRunRepository`` over SQLAlchemy."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...core import sql
from ...db import values
from ...db.generated.board import LOOP_GENERATION_RUNS_COLUMNS, LoopGenerationRunsRow
from ..errors import ConstraintViolationError

_RUN = (
    f"SELECT {sql.column_list(LOOP_GENERATION_RUNS_COLUMNS)}"  # noqa: S608 - generated columns
    " FROM loop_generation_runs"
)
_GET = text(f"{_RUN} WHERE id = :id")
_GET_IN_LOOP = text(f"{_RUN} WHERE id = :id AND loop_id = :loop_id")
_RECENT = text(f"{_RUN} WHERE loop_id = :id ORDER BY created_at DESC, rowid DESC LIMIT :limit")
_ACTIVE = text(
    f"{_RUN} WHERE loop_id = :loop_id AND purpose = :purpose AND status IN ('queued','running')"
)
_UNFINISHED = text("SELECT id FROM loop_generation_runs WHERE status IN ('queued','running')")
_ADD = text(
    "INSERT INTO loop_generation_runs (id, loop_id, purpose, status, input_json, input_hash,"
    " source_revisions_json, output_json, error_code, error_message, attempts, agent_id,"
    " agent_name, model, role_snapshot_json, usage_json, created_by_actor_id,"
    " created_by_actor_type, created_at, started_at, finished_at, phase, trace_json)"
    " VALUES (:id, :loop_id, :purpose, :status, :input_json, :input_hash,"
    " :source_revisions_json, :output_json, :error_code, :error_message, :attempts, :agent_id,"
    " :agent_name, :model, :role_snapshot_json, :usage_json, :created_by_actor_id,"
    " :created_by_actor_type, :created_at, :started_at, :finished_at, :phase, :trace_json)"
)
_CANCEL = text(
    "UPDATE loop_generation_runs SET status = 'cancelled', finished_at = :now WHERE id = :id"
)
_START = text(
    "UPDATE loop_generation_runs SET status = 'running', started_at = :now,"
    " attempts = attempts + 1, phase = 'reading_info' WHERE id = :id"
)
_SET_PHASE = text("UPDATE loop_generation_runs SET phase = :phase WHERE id = :id")
_SET_TRACE = text("UPDATE loop_generation_runs SET trace_json = :trace WHERE id = :id")
_STATUS = text("SELECT status FROM loop_generation_runs WHERE id = :id")
_SET_INPUT = text(
    "UPDATE loop_generation_runs SET input_json = :input, input_hash = :hash,"
    " source_revisions_json = :sources WHERE id = :id AND loop_id = :loop_id"
)
_COMPLETE = text(
    "UPDATE loop_generation_runs SET status = 'completed', output_json = :output,"
    " usage_json = :usage, model = :model, finished_at = :now WHERE id = :id"
)
_FAIL_INPUT_CHANGED = text(
    "UPDATE loop_generation_runs SET status = 'failed', error_code = 'generation_input_changed',"
    " error_message = :message, output_json = :output, finished_at = :now WHERE id = :id"
)
_FINISH = text(
    "UPDATE loop_generation_runs SET status = :status, error_code = :code,"
    " error_message = :message, output_json = :output, finished_at = :now WHERE id = :id"
)
_INTERRUPT = text(
    "UPDATE loop_generation_runs SET status = 'failed', error_code = 'interrupted',"
    " error_message = :message, finished_at = :now WHERE id = :id"
)


class SqlGenerationRunRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, run_id: str) -> LoopGenerationRunsRow | None:
        row = self._connection.execute(_GET, {"id": run_id}).mappings().first()
        return None if row is None else LoopGenerationRunsRow.from_mapping(row)

    def get_in_loop(self, loop_id: str, run_id: str) -> LoopGenerationRunsRow | None:
        parameters = {"id": run_id, "loop_id": loop_id}
        row = self._connection.execute(_GET_IN_LOOP, parameters).mappings().first()
        return None if row is None else LoopGenerationRunsRow.from_mapping(row)

    def recent(self, loop_id: str, *, limit: int) -> list[LoopGenerationRunsRow]:
        result = self._connection.execute(_RECENT, {"id": loop_id, "limit": limit}).mappings()
        return [LoopGenerationRunsRow.from_mapping(row) for row in result]

    def active(self, loop_id: str, purpose: str) -> LoopGenerationRunsRow | None:
        parameters = {"loop_id": loop_id, "purpose": purpose}
        row = self._connection.execute(_ACTIVE, parameters).mappings().first()
        return None if row is None else LoopGenerationRunsRow.from_mapping(row)

    def unfinished_ids(self) -> list[str]:
        return [values.text(row, "id") for row in self._connection.execute(_UNFINISHED).mappings()]

    def add(self, row: LoopGenerationRunsRow) -> None:
        try:
            self._connection.execute(_ADD, asdict(row))
        except IntegrityError as exc:
            raise ConstraintViolationError(str(exc.orig)) from exc

    def cancel(self, run_id: str, *, now: str) -> None:
        self._connection.execute(_CANCEL, {"now": now, "id": run_id})

    def start(self, run_id: str, *, now: str) -> None:
        self._connection.execute(_START, {"now": now, "id": run_id})

    def set_phase(self, run_id: str, phase: str) -> None:
        self._connection.execute(_SET_PHASE, {"phase": phase, "id": run_id})

    def set_trace(self, run_id: str, trace_json: str) -> str | None:
        self._connection.execute(_SET_TRACE, {"trace": trace_json, "id": run_id})
        row = self._connection.execute(_STATUS, {"id": run_id}).mappings().first()
        return None if row is None else values.text(row, "status")

    def set_input(
        self,
        loop_id: str,
        run_id: str,
        *,
        input_json: str,
        input_hash: str,
        source_revisions_json: str,
    ) -> None:
        parameters = {
            "input": input_json,
            "hash": input_hash,
            "sources": source_revisions_json,
            "id": run_id,
            "loop_id": loop_id,
        }
        self._connection.execute(_SET_INPUT, parameters)

    def complete(
        self, run_id: str, *, output_json: str, usage_json: str, model: str | None, now: str
    ) -> None:
        parameters = {
            "output": output_json,
            "usage": usage_json,
            "model": model,
            "now": now,
            "id": run_id,
        }
        self._connection.execute(_COMPLETE, parameters)

    def fail_input_changed(
        self, run_id: str, *, message: str, output_json: str, now: str
    ) -> None:
        parameters = {"message": message, "output": output_json, "now": now, "id": run_id}
        self._connection.execute(_FAIL_INPUT_CHANGED, parameters)

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
        output_json: str,
        now: str,
    ) -> None:
        parameters = {
            "status": status,
            "code": error_code,
            "message": error_message,
            "output": output_json,
            "now": now,
            "id": run_id,
        }
        self._connection.execute(_FINISH, parameters)

    def interrupt(self, run_id: str, *, message: str, now: str) -> None:
        self._connection.execute(_INTERRUPT, {"message": message, "now": now, "id": run_id})
