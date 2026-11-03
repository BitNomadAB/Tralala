"""A Loop's QA cycles, as the Loop summary and the Ticket rules read and change them.

``loop_id=None`` means every Loop of the board: the overview reads all Loops in one statement
instead of one per Loop.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopQaCyclesRow, LoopQaResultsRow


class LoopQaRepository(Protocol):
    def cycles(self, loop_id: str | None) -> list[LoopQaCyclesRow]:
        """The cycles by cycle number."""
        ...

    def supersede_open(self, loop_id: str, *, now: str) -> None:
        """Every cycle still pending, ready or in progress becomes ``superseded``."""
        ...

    def add(self, row: LoopQaCyclesRow) -> None: ...

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
        """The cycle's instructions are ready: both views, their revision and the baseline."""
        ...

    def mark_in_progress(self, cycle_id: str, *, now: str) -> None: ...

    def decide(self, cycle_id: str, *, status: str, actor_id: str, note: str, now: str) -> None:
        """A person accepted or rejected the cycle."""
        ...

    def results(self, cycle_id: str) -> list[LoopQaResultsRow]:
        """The cycle's results in the order they were recorded."""
        ...

    def add_result(self, row: LoopQaResultsRow) -> None: ...

    def approve_not_applicable(
        self, cycle_id: str, scenario_id: str, *, actor_id: str, note: str
    ) -> None:
        """A person accepts a scenario reported as not applicable."""
        ...
