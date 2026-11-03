"""A Loop's planning documents and the human decisions about them, as the Loop's stage reads them.

``loop_id=None`` means every Loop of the board: the overview reads all Loops in one statement
instead of one per Loop.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow


class LoopDocumentRepository(Protocol):
    def current_or_approved(self, loop_id: str | None) -> list[LoopDocumentsRow]:
        """The current and the approved revision of each document, by kind, then revision."""
        ...


class LoopApprovalRepository(Protocol):
    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        """Every decision, superseded ones included, newest first (by time, then insertion)."""
        ...
