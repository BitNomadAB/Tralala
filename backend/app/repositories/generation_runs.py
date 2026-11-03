"""A Loop's generation runs, as ``LoopGenerationService`` queues, runs, promotes and recovers them.

A run is queued, then running, and ends completed, failed or cancelled. A Loop has at most one
queued or running run per purpose: the database refuses a second one (``ux_loop_runs_active``).
No write is guarded by the run's status; the service reads the run first and decides.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopGenerationRunsRow


class GenerationRunRepository(Protocol):
    def get(self, run_id: str) -> LoopGenerationRunsRow | None: ...

    def get_in_loop(self, loop_id: str, run_id: str) -> LoopGenerationRunsRow | None:
        """The Loop's run; a run of another Loop is None."""
        ...

    def recent(self, loop_id: str, *, limit: int) -> list[LoopGenerationRunsRow]:
        """The Loop's runs, newest first (the later insert first on a tie), at most ``limit``."""
        ...

    def active(self, loop_id: str, purpose: str) -> LoopGenerationRunsRow | None:
        """The Loop's queued or running run for ``purpose``; there is at most one."""
        ...

    def unfinished_ids(self) -> list[str]:
        """Every queued or running run of the board, in no particular order."""
        ...

    def add(self, row: LoopGenerationRunsRow) -> None:
        """Every column as the row has it; a new run is ``queued`` with output and usage ``{}``, no
        attempts and no error, times or phase. Raises ``ConstraintViolationError`` when the Loop
        already has a queued or running run for the row's purpose."""
        ...

    def cancel(self, run_id: str, *, now: str) -> None:
        """``cancelled``, finished at ``now``."""
        ...

    def start(self, run_id: str, *, now: str) -> None:
        """``running``, started at ``now``, one more attempt, phase ``reading_info``."""
        ...

    def set_phase(self, run_id: str, phase: str) -> None: ...

    def set_trace(self, run_id: str, trace_json: str) -> str | None:
        """The run's steps so far (``trace_json``); answers the run's status after the write, so the
        run that records a step learns that it was cancelled, or None for a run that does not
        exist."""
        ...

    def set_input(
        self,
        loop_id: str,
        run_id: str,
        *,
        input_json: str,
        input_hash: str,
        source_revisions_json: str,
    ) -> None:
        """The input as the model receives it; a run of another Loop is left as it is."""
        ...

    def complete(
        self, run_id: str, *, output_json: str, usage_json: str, model: str | None, now: str
    ) -> None:
        """``completed`` with its output, usage and model, finished at ``now``."""
        ...

    def fail_input_changed(
        self, run_id: str, *, message: str, output_json: str, now: str
    ) -> None:
        """``failed`` as ``generation_input_changed`` with ``message``, finished at ``now``; the
        output keeps the candidate that was not promoted."""
        ...

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
        """``status`` with that error code and message (each may be none) and that output (the
        error's details, or ``{}``), finished at ``now``."""
        ...

    def interrupt(self, run_id: str, *, message: str, now: str) -> None:
        """``failed`` as ``interrupted`` with ``message``, finished at ``now``."""
        ...
