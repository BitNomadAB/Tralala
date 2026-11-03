"""An in-memory ``GenerationRunRepository`` over a ``BoardState``, ordered as the SQL orders it.

The dictionary keeps insertion order, which stands in for SQLite's rowid order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.generated.board import LoopGenerationRunsRow
from app.repositories.errors import ConstraintViolationError
from tests.unit.fakes.registry import ConstraintError

if TYPE_CHECKING:
    from tests.unit.fakes.board import BoardState

# The statuses ux_loop_runs_active covers: one such run per Loop and purpose.
ACTIVE = ("queued", "running")


class FakeGenerationRunRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, run_id: str) -> LoopGenerationRunsRow | None:
        return self._state.generation_runs.get(run_id)

    def get_in_loop(self, loop_id: str, run_id: str) -> LoopGenerationRunsRow | None:
        row = self._state.generation_runs.get(run_id)
        return row if row is not None and row.loop_id == loop_id else None

    def recent(self, loop_id: str, *, limit: int) -> list[LoopGenerationRunsRow]:
        rows = [row for row in self._state.generation_runs.values() if row.loop_id == loop_id]
        # rowid DESC first; the stable sort then keeps it among runs created at the same time.
        rows.reverse()
        rows.sort(key=lambda row: row.created_at, reverse=True)
        # SQLite reads a negative LIMIT as no limit.
        return rows if limit < 0 else rows[:limit]

    def unfinished_ids(self) -> list[str]:
        return [row.id for row in self._state.generation_runs.values() if row.status in ACTIVE]

    def add(self, row: LoopGenerationRunsRow) -> None:
        if row.id in self._state.generation_runs:
            raise ConstraintError(f"loop_generation_runs.id {row.id} exists")
        if row.loop_id not in self._state.loops:
            raise ConstraintError(f"loop_generation_runs {row.id} names a Loop that does not exist")
        if row.status in ACTIVE and any(
            run.loop_id == row.loop_id and run.purpose == row.purpose and run.status in ACTIVE
            for run in self._state.generation_runs.values()
        ):
            raise ConstraintViolationError("ux_loop_runs_active: one active run per purpose")
        self._state.generation_runs[row.id] = row

    def cancel(self, run_id: str, *, now: str) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status="cancelled", finished_at=now
            )

    def start(self, run_id: str, *, now: str) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status="running", started_at=now, attempts=row.attempts + 1, phase="reading_info"
            )

    def set_phase(self, run_id: str, phase: str) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(phase=phase)

    def set_input(
        self,
        loop_id: str,
        run_id: str,
        *,
        input_json: str,
        input_hash: str,
        source_revisions_json: str,
    ) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None and row.loop_id == loop_id:
            self._state.generation_runs[run_id] = row.__replace__(
                input_json=input_json,
                input_hash=input_hash,
                source_revisions_json=source_revisions_json,
            )

    def complete(
        self, run_id: str, *, output_json: str, usage_json: str, model: str | None, now: str
    ) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status="completed",
                output_json=output_json,
                usage_json=usage_json,
                model=model,
                finished_at=now,
            )

    def fail_input_changed(
        self, run_id: str, *, message: str, output_json: str, now: str
    ) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status="failed",
                error_code="generation_input_changed",
                error_message=message,
                output_json=output_json,
                finished_at=now,
            )

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
        now: str,
    ) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status=status, error_code=error_code, error_message=error_message, finished_at=now
            )

    def interrupt(self, run_id: str, *, message: str, now: str) -> None:
        row = self._state.generation_runs.get(run_id)
        if row is not None:
            self._state.generation_runs[run_id] = row.__replace__(
                status="failed", error_code="interrupted", error_message=message, finished_at=now
            )
