"""``LoopDocumentRepository`` and ``LoopApprovalRepository`` over SQLAlchemy."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import (
    LOOP_APPROVALS_COLUMNS,
    LOOP_DOCUMENTS_COLUMNS,
    LoopApprovalsRow,
    LoopDocumentsRow,
)

# --- documents -----------------------------------------------------------------------------------

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
_CURRENT = text(
    f"SELECT {_DOCUMENTS} FROM loop_documents"  # noqa: S608 - from LOOP_DOCUMENTS_COLUMNS
    " WHERE loop_id = :id AND kind = :kind AND is_current = 1"
)
_COUNT = text(
    "SELECT COUNT(*) AS total FROM loop_documents WHERE loop_id = :id AND kind = :kind"
)
_PAGE = text(
    f"SELECT {_DOCUMENTS} FROM loop_documents"  # noqa: S608 - from LOOP_DOCUMENTS_COLUMNS
    " WHERE loop_id = :id AND kind = :kind"
    " ORDER BY revision_number DESC LIMIT :limit OFFSET :offset"
)
_NEXT_REVISION = text(
    "SELECT COALESCE(MAX(revision_number), 0) + 1 AS next FROM loop_documents"
    " WHERE loop_id = :id AND kind = :kind"
)
_CLEAR_CURRENT = text(
    "UPDATE loop_documents SET is_current = 0 WHERE loop_id = :id AND kind = :kind"
)
_WITHDRAW_APPROVAL = text(
    "UPDATE loop_documents SET is_approved = 0 WHERE loop_id = :id AND kind = :kind"
)
_ADD = text(
    "INSERT INTO loop_documents (id, loop_id, kind, revision_number, content, payload_json,"
    " content_hash, status, source_info_revision_id, source_analysis_ai_revision_id,"
    " source_analysis_revision_id, source_roadmap_ai_revision_id, generation_run_id,"
    " author_actor_id, author_actor_type, author_name, provenance_json, is_current,"
    " is_approved, created_at) VALUES (:id, :loop_id, :kind, :revision_number, :content,"
    " :payload_json, :content_hash, :status, :source_info_revision_id,"
    " :source_analysis_ai_revision_id, :source_analysis_revision_id,"
    " :source_roadmap_ai_revision_id, :generation_run_id, :author_actor_id, :author_actor_type,"
    " :author_name, :provenance_json, :is_current, :is_approved, :created_at)"
)
_APPROVE = text(
    "UPDATE loop_documents SET is_approved = 1, status = 'approved' WHERE id = :id"
)
_REQUEST_CHANGES = text(
    "UPDATE loop_documents SET is_approved = 0, status = 'changes_requested' WHERE id = :id"
)

# --- approvals -----------------------------------------------------------------------------------

_APPROVALS = sql.column_list(LOOP_APPROVALS_COLUMNS)
_NEWEST_FIRST = text(
    f"SELECT {_APPROVALS} FROM loop_approvals"  # noqa: S608 - from LOOP_APPROVALS_COLUMNS
    " WHERE loop_id = :id ORDER BY created_at DESC, rowid DESC"
)
_ALL_NEWEST_FIRST = text(
    f"SELECT {_APPROVALS} FROM loop_approvals"  # noqa: S608 - from LOOP_APPROVALS_COLUMNS
    " WHERE loop_id IN (SELECT id FROM loops) ORDER BY created_at DESC, rowid DESC"
)
_GET_APPROVAL = text(f"SELECT {_APPROVALS} FROM loop_approvals WHERE id = :id")  # noqa: S608 - from LOOP_APPROVALS_COLUMNS
_ADD_APPROVAL = text(
    "INSERT INTO loop_approvals (id, loop_id, scope, decision, reviewer_actor_id, reviewer_name,"
    " feedback, revisions_json, source_hashes_json, loop_version, superseded_at, created_at)"
    " VALUES (:id, :loop_id, :scope, :decision, :reviewer_actor_id, :reviewer_name, :feedback,"
    " :revisions_json, :source_hashes_json, :loop_version, :superseded_at, :created_at)"
)
_SUPERSEDE_OTHERS = text(
    "UPDATE loop_approvals SET superseded_at = :now WHERE loop_id = :loop_id"
    " AND scope = :scope AND id != :id AND superseded_at IS NULL"
)
_SUPERSEDE = text("UPDATE loop_approvals SET superseded_at = :now WHERE id = :id")


class SqlLoopDocumentRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def current_or_approved(self, loop_id: str | None) -> list[LoopDocumentsRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_CURRENT_OR_APPROVED)
        else:
            result = self._connection.execute(_CURRENT_OR_APPROVED, {"id": loop_id})
        return [LoopDocumentsRow.from_mapping(row) for row in result.mappings()]

    def current(self, loop_id: str, kind: str) -> LoopDocumentsRow | None:
        parameters = {"id": loop_id, "kind": kind}
        row = self._connection.execute(_CURRENT, parameters).mappings().first()
        return None if row is None else LoopDocumentsRow.from_mapping(row)

    def count(self, loop_id: str, kind: str) -> int:
        row = self._connection.execute(_COUNT, {"id": loop_id, "kind": kind}).mappings().one()
        return values.integer(row, "total")

    def page(self, loop_id: str, kind: str, *, limit: int, offset: int) -> list[LoopDocumentsRow]:
        parameters = {"id": loop_id, "kind": kind, "limit": limit, "offset": offset}
        result = self._connection.execute(_PAGE, parameters)
        return [LoopDocumentsRow.from_mapping(row) for row in result.mappings()]

    def next_revision(self, loop_id: str, kind: str) -> int:
        parameters = {"id": loop_id, "kind": kind}
        row = self._connection.execute(_NEXT_REVISION, parameters).mappings().one()
        return values.integer(row, "next")

    def clear_current(self, loop_id: str, kind: str) -> None:
        self._connection.execute(_CLEAR_CURRENT, {"id": loop_id, "kind": kind})

    def withdraw_approval(self, loop_id: str, kind: str) -> None:
        self._connection.execute(_WITHDRAW_APPROVAL, {"id": loop_id, "kind": kind})

    def add(self, row: LoopDocumentsRow) -> None:
        self._connection.execute(
            _ADD,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "kind": row.kind,
                "revision_number": row.revision_number,
                "content": row.content,
                "payload_json": row.payload_json,
                "content_hash": row.content_hash,
                "status": row.status,
                "source_info_revision_id": row.source_info_revision_id,
                "source_analysis_ai_revision_id": row.source_analysis_ai_revision_id,
                "source_analysis_revision_id": row.source_analysis_revision_id,
                "source_roadmap_ai_revision_id": row.source_roadmap_ai_revision_id,
                "generation_run_id": row.generation_run_id,
                "author_actor_id": row.author_actor_id,
                "author_actor_type": row.author_actor_type,
                "author_name": row.author_name,
                "provenance_json": row.provenance_json,
                "is_current": row.is_current,
                "is_approved": row.is_approved,
                "created_at": row.created_at,
            },
        )

    def approve(self, document_id: str) -> None:
        self._connection.execute(_APPROVE, {"id": document_id})

    def request_changes(self, document_id: str) -> None:
        self._connection.execute(_REQUEST_CHANGES, {"id": document_id})


class SqlLoopApprovalRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def newest_first(self, loop_id: str | None) -> list[LoopApprovalsRow]:
        if loop_id is None:
            result = self._connection.execute(_ALL_NEWEST_FIRST)
        else:
            result = self._connection.execute(_NEWEST_FIRST, {"id": loop_id})
        return [LoopApprovalsRow.from_mapping(row) for row in result.mappings()]

    def get(self, approval_id: str) -> LoopApprovalsRow | None:
        row = self._connection.execute(_GET_APPROVAL, {"id": approval_id}).mappings().first()
        return None if row is None else LoopApprovalsRow.from_mapping(row)

    def add(self, row: LoopApprovalsRow) -> None:
        self._connection.execute(
            _ADD_APPROVAL,
            {
                "id": row.id,
                "loop_id": row.loop_id,
                "scope": row.scope,
                "decision": row.decision,
                "reviewer_actor_id": row.reviewer_actor_id,
                "reviewer_name": row.reviewer_name,
                "feedback": row.feedback,
                "revisions_json": row.revisions_json,
                "source_hashes_json": row.source_hashes_json,
                "loop_version": row.loop_version,
                "superseded_at": row.superseded_at,
                "created_at": row.created_at,
            },
        )

    def supersede_others(self, loop_id: str, scope: str, *, keep: str, now: str) -> None:
        self._connection.execute(
            _SUPERSEDE_OTHERS, {"now": now, "loop_id": loop_id, "scope": scope, "id": keep}
        )

    def supersede(self, approval_id: str, *, now: str) -> None:
        self._connection.execute(_SUPERSEDE, {"now": now, "id": approval_id})
