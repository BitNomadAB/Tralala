"""A Loop's planning documents and the human decisions about them.

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

    def current(self, loop_id: str, kind: str) -> LoopDocumentsRow | None:
        """The kind's current revision."""
        ...

    def count(self, loop_id: str, kind: str) -> int: ...

    def page(self, loop_id: str, kind: str, *, limit: int, offset: int) -> list[LoopDocumentsRow]:
        """The kind's revisions, newest first, ``limit`` from ``offset``."""
        ...

    def next_revision(self, loop_id: str, kind: str) -> int:
        """One more than the kind's highest revision number (1 for its first)."""
        ...

    def clear_current(self, loop_id: str, kind: str) -> None:
        """No revision of the kind is current any more."""
        ...

    def withdraw_approval(self, loop_id: str, kind: str) -> None:
        """No revision of the kind is approved any more; their status stays."""
        ...

    def add(self, row: LoopDocumentsRow) -> None: ...

    def approve(self, document_id: str) -> None:
        """The revision is approved (flag and status)."""
        ...

    def request_changes(self, document_id: str) -> None:
        """The revision is not approved and its status asks for changes."""
        ...


class LoopApprovalRepository(Protocol):
    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        """Every decision, superseded ones included, newest first (by time, then insertion)."""
        ...

    def get(self, approval_id: str) -> LoopApprovalsRow | None: ...

    def add(self, row: LoopApprovalsRow) -> None: ...

    def supersede_others(self, loop_id: str, scope: str, *, keep: str, now: str) -> None:
        """Every other decision of the scope that nobody superseded yet is superseded at ``now``."""
        ...

    def supersede(self, approval_id: str, *, now: str) -> None: ...
