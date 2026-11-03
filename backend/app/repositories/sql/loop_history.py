"""The Loop history repositories over SQLAlchemy."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import (
    ACTIVITY_LOG_COLUMNS,
    ATTACHMENTS_COLUMNS,
    CARDS_COLUMNS,
    COMMENTS_COLUMNS,
    LOOP_APPROVALS_COLUMNS,
    LOOP_DEPENDENCIES_COLUMNS,
    LOOP_DOCUMENTS_COLUMNS,
    LOOP_GENERATION_RUNS_COLUMNS,
    LOOP_HISTORY_COLUMNS,
    LOOP_PHASES_COLUMNS,
    LOOP_PLAN_ITEMS_COLUMNS,
    LOOP_PLANS_COLUMNS,
    LOOP_QA_CYCLES_COLUMNS,
    LOOP_QA_RESULTS_COLUMNS,
    ActivityLogRow,
    AttachmentsRow,
    CardsRow,
    CommentsRow,
    LoopApprovalsRow,
    LoopDependenciesRow,
    LoopDocumentsRow,
    LoopGenerationRunsRow,
    LoopHistoryArtifactsRow,
    LoopHistoryRow,
    LoopPhasesRow,
    LoopPlanItemsRow,
    LoopPlansRow,
    LoopQaCyclesRow,
    LoopQaResultsRow,
)
from ..loop_history import (
    ArtifactSummary,
    ChecklistLine,
    HistoryQuery,
    ImportedHistory,
    NativeHistory,
)

# --- the snapshot's sources ----------------------------------------------------------------------

_DOCUMENTS = text(
    f"SELECT {sql.column_list(LOOP_DOCUMENTS_COLUMNS)} FROM loop_documents"  # noqa: S608 - generated
    " WHERE loop_id = :id ORDER BY kind, revision_number"
)
_APPROVALS = text(
    f"SELECT {sql.column_list(LOOP_APPROVALS_COLUMNS)} FROM loop_approvals"  # noqa: S608 - generated
    " WHERE loop_id = :id ORDER BY created_at"
)
_PLANS = text(
    f"SELECT {sql.column_list(LOOP_PLANS_COLUMNS)} FROM loop_plans"  # noqa: S608 - generated
    " WHERE loop_id = :id ORDER BY revision_number"
)
_PHASES = text(
    f"SELECT {sql.column_list(LOOP_PHASES_COLUMNS)} FROM loop_phases"  # noqa: S608 - generated
    " WHERE loop_id = :id ORDER BY number"
)
_PLAN_ITEMS = text(
    f"SELECT {sql.column_list(LOOP_PLAN_ITEMS_COLUMNS)} FROM loop_plan_items"  # noqa: S608
    " WHERE loop_id = :id ORDER BY phase_number, ticket_sequence"
)
_DEPENDENCIES = text(
    f"SELECT {sql.column_list(LOOP_DEPENDENCIES_COLUMNS)} FROM loop_dependencies"  # noqa: S608
    " WHERE loop_id = :id"
)
_TICKETS = text(
    f"SELECT {sql.column_list(CARDS_COLUMNS)} FROM cards"  # noqa: S608 - generated
    " WHERE loop_id = :id ORDER BY ticket_key, created_at"
)
_COMMENTS = text(
    f"SELECT {sql.column_list(COMMENTS_COLUMNS, 'c')} FROM comments c"  # noqa: S608 - generated
    " JOIN cards k ON k.id = c.card_id WHERE k.loop_id = :id ORDER BY c.created_at"
)
_CHECKLIST_LINES = text(
    "SELECT ch.card_id, ch.title, i.text, i.completed FROM checklists ch"
    " JOIN cards k ON k.id = ch.card_id LEFT JOIN checklist_items i ON i.checklist_id = ch.id"
    " WHERE k.loop_id = :id ORDER BY ch.card_id, ch.position, i.position"
)
_QA_CYCLES = text(
    f"SELECT {sql.column_list(LOOP_QA_CYCLES_COLUMNS)} FROM loop_qa_cycles"  # noqa: S608
    " WHERE loop_id = :id ORDER BY cycle_number"
)
_QA_RESULTS = text(
    f"SELECT {sql.column_list(LOOP_QA_RESULTS_COLUMNS, 'r')} FROM loop_qa_results r"  # noqa: S608
    " JOIN loop_qa_cycles c ON c.id = r.cycle_id WHERE c.loop_id = :id ORDER BY r.created_at"
)
_GENERATION_RUNS = text(
    f"SELECT {sql.column_list(LOOP_GENERATION_RUNS_COLUMNS)} FROM loop_generation_runs"  # noqa: S608
    " WHERE loop_id = :id ORDER BY created_at"
)
_ACTIVITY = text(
    f"SELECT {sql.column_list(ACTIVITY_LOG_COLUMNS)} FROM activity_log"  # noqa: S608 - generated
    " WHERE entity_type = 'loop' AND entity_id = :id ORDER BY timestamp"
)
_ATTACHMENTS = text(
    f"SELECT {sql.column_list(ATTACHMENTS_COLUMNS, 'a')} FROM attachments a"  # noqa: S608
    " JOIN cards k ON k.id = a.card_id WHERE k.loop_id = :id AND a.deleted_at IS NULL"
    " ORDER BY a.created_at"
)


class SqlLoopArchiveRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def documents(self, loop_id: str) -> list[LoopDocumentsRow]:
        result = self._connection.execute(_DOCUMENTS, {"id": loop_id}).mappings()
        return [LoopDocumentsRow.from_mapping(row) for row in result]

    def approvals(self, loop_id: str) -> list[LoopApprovalsRow]:
        result = self._connection.execute(_APPROVALS, {"id": loop_id}).mappings()
        return [LoopApprovalsRow.from_mapping(row) for row in result]

    def plans(self, loop_id: str) -> list[LoopPlansRow]:
        result = self._connection.execute(_PLANS, {"id": loop_id}).mappings()
        return [LoopPlansRow.from_mapping(row) for row in result]

    def phases(self, loop_id: str) -> list[LoopPhasesRow]:
        result = self._connection.execute(_PHASES, {"id": loop_id}).mappings()
        return [LoopPhasesRow.from_mapping(row) for row in result]

    def plan_items(self, loop_id: str) -> list[LoopPlanItemsRow]:
        result = self._connection.execute(_PLAN_ITEMS, {"id": loop_id}).mappings()
        return [LoopPlanItemsRow.from_mapping(row) for row in result]

    def dependencies(self, loop_id: str) -> list[LoopDependenciesRow]:
        result = self._connection.execute(_DEPENDENCIES, {"id": loop_id}).mappings()
        return [LoopDependenciesRow.from_mapping(row) for row in result]

    def tickets(self, loop_id: str) -> list[CardsRow]:
        result = self._connection.execute(_TICKETS, {"id": loop_id}).mappings()
        return [CardsRow.from_mapping(row) for row in result]

    def comments(self, loop_id: str) -> list[CommentsRow]:
        result = self._connection.execute(_COMMENTS, {"id": loop_id}).mappings()
        return [CommentsRow.from_mapping(row) for row in result]

    def checklist_lines(self, loop_id: str) -> list[ChecklistLine]:
        result = self._connection.execute(_CHECKLIST_LINES, {"id": loop_id}).mappings()
        return [
            {
                "card_id": values.text(row, "card_id"),
                "title": values.text(row, "title"),
                "text": values.text_or_none(row, "text"),
                "completed": values.integer_or_none(row, "completed"),
            }
            for row in result
        ]

    def qa_cycles(self, loop_id: str) -> list[LoopQaCyclesRow]:
        result = self._connection.execute(_QA_CYCLES, {"id": loop_id}).mappings()
        return [LoopQaCyclesRow.from_mapping(row) for row in result]

    def qa_results(self, loop_id: str) -> list[LoopQaResultsRow]:
        result = self._connection.execute(_QA_RESULTS, {"id": loop_id}).mappings()
        return [LoopQaResultsRow.from_mapping(row) for row in result]

    def generation_runs(self, loop_id: str) -> list[LoopGenerationRunsRow]:
        result = self._connection.execute(_GENERATION_RUNS, {"id": loop_id}).mappings()
        return [LoopGenerationRunsRow.from_mapping(row) for row in result]

    def activity(self, loop_id: str) -> list[ActivityLogRow]:
        result = self._connection.execute(_ACTIVITY, {"id": loop_id}).mappings()
        return [ActivityLogRow.from_mapping(row) for row in result]

    def attachments(self, loop_id: str) -> list[AttachmentsRow]:
        result = self._connection.execute(_ATTACHMENTS, {"id": loop_id}).mappings()
        return [AttachmentsRow.from_mapping(row) for row in result]


# --- the stored snapshots ------------------------------------------------------------------------

_HISTORY = sql.column_list(LOOP_HISTORY_COLUMNS)
_HISTORY_H = sql.column_list(LOOP_HISTORY_COLUMNS, "h")
_GET = text(f"SELECT {_HISTORY} FROM loop_history WHERE id = :id")  # noqa: S608 - generated
_NATIVE_FOR = text(
    f"SELECT {_HISTORY} FROM loop_history"  # noqa: S608 - from LOOP_HISTORY_COLUMNS
    " WHERE board_id = :board AND loop_id = :loop AND source_kind = 'native'"
)
_ADD_NATIVE = text(
    "INSERT INTO loop_history (id, history_schema_version, source_kind, conformance, board_id,"
    " loop_id, loop_key, loop_name, qa_status, envelope_json, search_text, content_hash,"
    " completed_at, created_at) VALUES (:id, :history_schema_version, 'native', 'native',"
    " :board_id, :loop_id, :loop_key, :loop_name, :qa_status, :envelope_json, :search_text,"
    " :content_hash, :now, :now)"
)
_ADD_IMPORTED = text(
    "INSERT INTO loop_history (id, history_schema_version, source_kind, conformance, board_id,"
    " loop_id, loop_key, loop_name, qa_status, envelope_json, search_text, content_hash,"
    " imported_at, imported_by_actor_id, source_project, source_reference, source_format,"
    " source_version, validation_warnings_json, created_at) VALUES (:id,"
    " :history_schema_version, 'imported_legacy', 'legacy_unvalidated', :board_id, NULL, NULL,"
    " :loop_name, :qa_status, :envelope_json, :search_text, :content_hash, :now,"
    " :imported_by_actor_id, :source_project, :source_reference, :source_format,"
    " :source_version, :validation_warnings_json, :now)"
)
_SEAL = text(
    "UPDATE loop_history SET envelope_json = :envelope, content_hash = :hash WHERE id = :id"
)
_ADD_ARTIFACT = text(
    "INSERT INTO loop_history_artifacts (id, history_id, filename, media_type, content_hash,"
    " size_bytes, inclusion, data) VALUES (:id, :history_id, :filename, :media_type,"
    " :content_hash, :size_bytes, :inclusion, :data)"
)
_ARTIFACTS = text(
    "SELECT id, filename, media_type, content_hash, size_bytes, inclusion"
    " FROM loop_history_artifacts WHERE history_id = :id ORDER BY filename"
)
# What the history search formats into SQL text (see core/sql.py).
_HISTORY_JOINS = ("", " JOIN loop_history_fts f ON f.rowid = h.rowid")
_HISTORY_FILTERS: sql.Filters = (
    ("match", "loop_history_fts MATCH :match"),
    ("q", "(h.search_text LIKE :q OR h.loop_name LIKE :q)"),
    ("source_kind", "h.source_kind = :source_kind"),
    ("loop_key", "(h.loop_key = :loop_key OR h.loop_name LIKE :loop_key_like)"),
    ("qa_status", "h.qa_status = :qa_status"),
    ("date_from", "COALESCE(h.completed_at, h.imported_at, h.created_at) >= :date_from"),
    ("date_to", "COALESCE(h.completed_at, h.imported_at, h.created_at) <= :date_to"),
)



class SqlLoopHistoryRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, history_id: str) -> LoopHistoryRow | None:
        row = self._connection.execute(_GET, {"id": history_id}).mappings().first()
        return None if row is None else LoopHistoryRow.from_mapping(row)

    def native_for(self, board_id: str, loop_id: str) -> LoopHistoryRow | None:
        parameters = {"board": board_id, "loop": loop_id}
        row = self._connection.execute(_NATIVE_FOR, parameters).mappings().first()
        return None if row is None else LoopHistoryRow.from_mapping(row)

    def add_native(self, entry: NativeHistory) -> None:
        self._connection.execute(_ADD_NATIVE, dict(entry))

    def add_imported(self, entry: ImportedHistory) -> None:
        self._connection.execute(_ADD_IMPORTED, dict(entry))

    def seal(self, history_id: str, *, envelope_json: str, content_hash: str) -> None:
        parameters = {"envelope": envelope_json, "hash": content_hash, "id": history_id}
        self._connection.execute(_SEAL, parameters)

    def add_artifact(self, row: LoopHistoryArtifactsRow) -> None:
        self._connection.execute(_ADD_ARTIFACT, asdict(row))

    def artifacts(self, history_id: str) -> list[ArtifactSummary]:
        result = self._connection.execute(_ARTIFACTS, {"id": history_id}).mappings()
        return [
            {
                "id": values.text(row, "id"),
                "filename": values.text(row, "filename"),
                "media_type": values.text(row, "media_type"),
                "content_hash": values.text(row, "content_hash"),
                "size_bytes": values.integer(row, "size_bytes"),
                "inclusion": values.text(row, "inclusion"),
            }
            for row in result
        ]

    def count(self, query: HistoryQuery, *, fts: bool) -> int:
        join = sql.identifier(_HISTORY_JOINS[1] if fts else "", _HISTORY_JOINS)
        where = sql.where(_HISTORY_FILTERS, [name for name, _ in _HISTORY_FILTERS if name in query])
        statement = text(
            f"SELECT COUNT(DISTINCT h.id) FROM loop_history h{join}{where}"  # noqa: S608 - from _HISTORY_JOINS and _HISTORY_FILTERS
        )
        return int(self._connection.execute(statement, dict(query)).scalar_one())

    def page(
        self, query: HistoryQuery, *, fts: bool, limit: int, offset: int
    ) -> list[LoopHistoryRow]:
        join = sql.identifier(_HISTORY_JOINS[1] if fts else "", _HISTORY_JOINS)
        where = sql.where(_HISTORY_FILTERS, [name for name, _ in _HISTORY_FILTERS if name in query])
        statement = text(
            f"SELECT DISTINCT {_HISTORY_H} FROM loop_history h{join}{where}"  # noqa: S608 - from _HISTORY_JOINS and _HISTORY_FILTERS
            " ORDER BY COALESCE(h.completed_at, h.imported_at, h.created_at) DESC, h.id"
            " LIMIT :limit OFFSET :offset"
        )
        parameters = {**query, "limit": limit, "offset": offset}
        result = self._connection.execute(statement, parameters).mappings()
        return [LoopHistoryRow.from_mapping(row) for row in result]
