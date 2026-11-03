"""TRANSITIONAL bridge between the converted Loop and Ticket services and the Loop workflow
services that still hold a connection. GCS-T00f removes this module when it converts them.

``LoopConnectionHelpers`` gives ``loop_documents``, ``loop_qa`` and ``loop_generation`` the
dict-on-connection helpers LoopService used to have, under the same names and signatures. Each one
runs the typed rule of ``services/loops.py`` on ``SqlBoardRepositories`` over the caller's
connection, so it is the same transaction, and hands back the dicts those services read (a row's
columns in table order, as ``SELECT *`` gave them). Dicts they pass back in are read through the
generated rows' checked ``from_mapping``.

The module is outside the pyright strict scope on purpose and is listed in the GCS-T00e and
GCS-T00f notes.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.engine import Connection

from ..core.dates import utcnow
from ..db.generated.board import LoopApprovalsRow, LoopDocumentsRow, LoopsRow
from ..repositories.sql.board import SqlBoardRepositories
from . import loops

# The former signatures, loose as they were, so the callers read the same types as before.
type Row = dict[str, Any]
type Documents = dict[str, dict[str, Any]]


def _row(value: LoopDocumentsRow | None) -> Row | None:
    return None if value is None else asdict(value)


def _slots(documents: Documents) -> loops.DocumentSlots:
    return {
        kind: loops.DocumentSlot(
            current=_document(slot["current"]), approved=_document(slot["approved"])
        )
        for kind, slot in documents.items()
    }


def _document(row: Row | None) -> LoopDocumentsRow | None:
    return None if row is None else LoopDocumentsRow.from_mapping(row)


def _approvals(approvals: dict[str, Row]) -> loops.Approvals:
    return {scope: LoopApprovalsRow.from_mapping(row) for scope, row in approvals.items()}


class LoopConnectionHelpers:
    """LoopService's former connection helpers for the services GCS-T00f converts."""

    def __init__(self, service: loops.LoopService) -> None:
        self._service = service

    def get(self, board_id: str, loop_id: str) -> Row:
        return dict(self._service.get(board_id, loop_id))

    @staticmethod
    def require_loop_row(conn: Connection, board_id: str, loop_id: str) -> Row:
        del board_id
        return asdict(loops.require_loop(SqlBoardRepositories(conn), loop_id))

    @staticmethod
    def ensure_writable(loop_row: Row) -> None:
        loops.ensure_writable(LoopsRow.from_mapping(loop_row))

    @staticmethod
    def ensure_execution_allowed(loop_row: Row) -> None:
        loops.ensure_execution_allowed(LoopsRow.from_mapping(loop_row))

    @staticmethod
    def refresh_stage(conn: Connection, loop_id: str) -> str:
        return loops.refresh_stage(SqlBoardRepositories(conn), loop_id, now=utcnow())

    @staticmethod
    def document_rows(conn: Connection, loop_id: str) -> Documents:
        """Current and approved revisions for each of the five slots."""
        records = SqlBoardRepositories(conn).documents.current_or_approved(loop_id)
        return {
            kind: {"current": _row(slot.current), "approved": _row(slot.approved)}
            for kind, slot in loops.document_slots(records).items()
        }

    @staticmethod
    def latest_approvals(conn: Connection, loop_id: str) -> dict[str, Row]:
        records = SqlBoardRepositories(conn).approvals.newest_first(loop_id)
        return {scope: asdict(row) for scope, row in loops.latest_approvals(records).items()}

    @staticmethod
    def _stale_reasons(documents: Documents, approvals: dict[str, Row]) -> dict[str, list[str]]:
        return loops.stale_reasons(_slots(documents), _approvals(approvals))

    @staticmethod
    def analysis_approved(
        documents: Documents, approvals: dict[str, Row], stale: dict[str, list[str]]
    ) -> bool:
        return loops.analysis_approved(_slots(documents), _approvals(approvals), stale)

    @staticmethod
    def _document_state(
        kind: str, documents: Documents, approvals: dict[str, Row], stale: dict[str, list[str]]
    ) -> Row:
        return dict(loops.document_state(kind, _slots(documents), _approvals(approvals), stale))
