"""``LoopDocumentRepository`` and ``LoopApprovalRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db.generated.board import (
    LOOP_APPROVALS_COLUMNS,
    LOOP_DOCUMENTS_COLUMNS,
    LoopApprovalsRow,
    LoopDocumentsRow,
)

_DOCUMENTS = sql.column_list(LOOP_DOCUMENTS_COLUMNS)
_CURRENT_OR_APPROVED = text(
    f"SELECT {_DOCUMENTS} FROM loop_documents"  # noqa: S608 - from LOOP_DOCUMENTS_COLUMNS
    " WHERE loop_id = :id AND (is_current = 1 OR is_approved = 1)"
    " ORDER BY kind, revision_number"
)
_ALL_CURRENT_OR_APPROVED = text(
    f"SELECT {_DOCUMENTS} FROM loop_documents"  # noqa: S608 - from LOOP_DOCUMENTS_COLUMNS
    " WHERE (is_current = 1 OR is_approved = 1) AND loop_id IN (SELECT id FROM loops)"
    " ORDER BY kind, revision_number"
)
_APPROVALS = sql.column_list(LOOP_APPROVALS_COLUMNS)
_NEWEST_FIRST = text(
    f"SELECT {_APPROVALS} FROM loop_approvals"  # noqa: S608 - from LOOP_APPROVALS_COLUMNS
    " WHERE loop_id = :id ORDER BY created_at DESC, rowid DESC"
)
_ALL_NEWEST_FIRST = text(
    f"SELECT {_APPROVALS} FROM loop_approvals"  # noqa: S608 - from LOOP_APPROVALS_COLUMNS
    " WHERE loop_id IN (SELECT id FROM loops) ORDER BY created_at DESC, rowid DESC"
)


class SqlLoopDocumentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def current_or_approved(self, loop_id: str | None) -> list[LoopDocumentsRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_CURRENT_OR_APPROVED)
        else:
            result = self._connection.execute(_CURRENT_OR_APPROVED, {"id": loop_id})
        return [LoopDocumentsRow.from_mapping(row) for row in result.mappings()]


class SqlLoopApprovalRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_NEWEST_FIRST)
        else:
            result = self._connection.execute(_NEWEST_FIRST, {"id": loop_id})
        return [LoopApprovalsRow.from_mapping(row) for row in result.mappings()]
