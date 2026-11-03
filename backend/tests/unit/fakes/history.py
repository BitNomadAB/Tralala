"""In-memory Loop archive and history repositories over a ``BoardState``, ordered as the SQL
orders them (SQLite puts NULL first in an ascending sort)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.db.generated.board import (
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
from app.repositories.loop_history import (
    ArtifactSummary,
    ChecklistLine,
    HistoryQuery,
    ImportedHistory,
    NativeHistory,
)
from tests.unit.fakes.registry import ConstraintError, like

if TYPE_CHECKING:
    from tests.unit.fakes.board import BoardState


def _nulls_first(value: str | None) -> tuple[bool, str]:
    return (value is not None, value or "")


class FakeLoopArchiveRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def _tickets(self, loop_id: str) -> set[str]:
        return {card.id for card in self._state.cards.values() if card.loop_id == loop_id}

    def documents(self, loop_id: str) -> list[LoopDocumentsRow]:
        rows = [row for row in self._state.documents if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: (row.kind, row.revision_number))

    def approvals(self, loop_id: str) -> list[LoopApprovalsRow]:
        rows = [row for row in self._state.approvals if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: row.created_at)

    def plans(self, loop_id: str) -> list[LoopPlansRow]:
        rows = [row for row in self._state.plans.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: row.revision_number)

    def phases(self, loop_id: str) -> list[LoopPhasesRow]:
        rows = [row for row in self._state.phases.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: row.number)

    def plan_items(self, loop_id: str) -> list[LoopPlanItemsRow]:
        rows = [row for row in self._state.plan_items.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: (row.phase_number, row.ticket_sequence))

    def dependencies(self, loop_id: str) -> list[LoopDependenciesRow]:
        return [row for row in self._state.dependencies if row.loop_id == loop_id]

    def tickets(self, loop_id: str) -> list[CardsRow]:
        rows = [row for row in self._state.cards.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: (_nulls_first(row.ticket_key), row.created_at))

    def comments(self, loop_id: str) -> list[CommentsRow]:
        tickets = self._tickets(loop_id)
        rows = [row for row in self._state.comments.values() if row.card_id in tickets]
        return sorted(rows, key=lambda row: row.created_at)

    def checklist_lines(self, loop_id: str) -> list[ChecklistLine]:
        tickets = self._tickets(loop_id)
        lists = sorted(
            (row for row in self._state.checklists.values() if row.card_id in tickets),
            key=lambda row: (row.card_id, row.position),
        )
        lines: list[ChecklistLine] = []
        for checklist in lists:
            items = sorted(
                (i for i in self._state.checklist_items.values() if i.checklist_id == checklist.id),
                key=lambda item: item.position,
            )
            if not items:
                lines.append(
                    {
                        "card_id": checklist.card_id,
                        "title": checklist.title,
                        "text": None,
                        "completed": None,
                    }
                )
            lines.extend(
                {
                    "card_id": checklist.card_id,
                    "title": checklist.title,
                    "text": item.text,
                    "completed": item.completed,
                }
                for item in items
            )
        return lines

    def qa_cycles(self, loop_id: str) -> list[LoopQaCyclesRow]:
        rows = [row for row in self._state.qa_cycles.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: row.cycle_number)

    def qa_results(self, loop_id: str) -> list[LoopQaResultsRow]:
        cycles = {row.id for row in self._state.qa_cycles.values() if row.loop_id == loop_id}
        rows = [row for row in self._state.qa_results if row.cycle_id in cycles]
        return sorted(rows, key=lambda row: row.created_at)

    def generation_runs(self, loop_id: str) -> list[LoopGenerationRunsRow]:
        rows = [row for row in self._state.generation_runs.values() if row.loop_id == loop_id]
        return sorted(rows, key=lambda row: row.created_at)

    def activity(self, loop_id: str) -> list[ActivityLogRow]:
        rows = [
            row
            for row in self._state.activity
            if row.entity_type == "loop" and row.entity_id == loop_id
        ]
        return sorted(rows, key=lambda row: row.timestamp)

    def attachments(self, loop_id: str) -> list[AttachmentsRow]:
        tickets = self._tickets(loop_id)
        rows = [
            row
            for row in self._state.attachments.values()
            if row.card_id in tickets and row.deleted_at is None
        ]
        return sorted(rows, key=lambda row: row.created_at)


def _moment(row: LoopHistoryRow) -> str:
    return row.completed_at or row.imported_at or row.created_at


_FTS_TOKEN = re.compile(r'"([^"]*)"\*')


def _fts(expression: str, row: LoopHistoryRow) -> bool:
    words = re.findall(r"\w+", f"{row.loop_name} {row.search_text}".casefold())
    tokens = [token.strip().casefold() for token in _FTS_TOKEN.findall(expression)]
    return all(any(word.startswith(token) for word in words) for token in tokens if token)


def _matches(row: LoopHistoryRow, query: HistoryQuery) -> bool:
    checks = [
        "match" not in query or _fts(query["match"], row),
        "q" not in query or like(row.search_text, query["q"]) or like(row.loop_name, query["q"]),
        "source_kind" not in query or row.source_kind == query["source_kind"],
        "loop_key" not in query
        or row.loop_key == query["loop_key"]
        or like(row.loop_name, query.get("loop_key_like", "")),
        "qa_status" not in query or row.qa_status == query["qa_status"],
        "date_from" not in query or _moment(row) >= query["date_from"],
        "date_to" not in query or _moment(row) <= query["date_to"],
    ]
    return all(checks)


class FakeLoopHistoryRepository:
    def __init__(self, state: BoardState) -> None:
        self._state = state

    def get(self, history_id: str) -> LoopHistoryRow | None:
        return self._state.history.get(history_id)

    def native_for(self, board_id: str, loop_id: str) -> LoopHistoryRow | None:
        return next(
            (
                row
                for row in self._state.history.values()
                if row.board_id == board_id
                and row.loop_id == loop_id
                and row.source_kind == "native"
            ),
            None,
        )

    def _add(self, row: LoopHistoryRow) -> None:
        if row.id in self._state.history:
            raise ConstraintError(f"loop_history.id {row.id} exists")
        self._state.history[row.id] = row

    def add_native(self, entry: NativeHistory) -> None:
        self._add(
            LoopHistoryRow(
                id=entry["id"],
                history_schema_version=entry["history_schema_version"],
                source_kind="native",
                conformance="native",
                board_id=entry["board_id"],
                loop_id=entry["loop_id"],
                loop_key=entry["loop_key"],
                loop_name=entry["loop_name"],
                qa_status=entry["qa_status"],
                envelope_json=entry["envelope_json"],
                search_text=entry["search_text"],
                content_hash=entry["content_hash"],
                completed_at=entry["now"],
                imported_at=None,
                imported_by_actor_id=None,
                source_project=None,
                source_reference=None,
                source_format=None,
                source_version=None,
                validation_warnings_json="[]",
                created_at=entry["now"],
            )
        )

    def add_imported(self, entry: ImportedHistory) -> None:
        self._add(
            LoopHistoryRow(
                id=entry["id"],
                history_schema_version=entry["history_schema_version"],
                source_kind="imported_legacy",
                conformance="legacy_unvalidated",
                board_id=entry["board_id"],
                loop_id=None,
                loop_key=None,
                loop_name=entry["loop_name"],
                qa_status=entry["qa_status"],
                envelope_json=entry["envelope_json"],
                search_text=entry["search_text"],
                content_hash=entry["content_hash"],
                completed_at=None,
                imported_at=entry["now"],
                imported_by_actor_id=entry["imported_by_actor_id"],
                source_project=entry["source_project"],
                source_reference=entry["source_reference"],
                source_format=entry["source_format"],
                source_version=entry["source_version"],
                validation_warnings_json=entry["validation_warnings_json"],
                created_at=entry["now"],
            )
        )

    def seal(self, history_id: str, *, envelope_json: str, content_hash: str) -> None:
        row = self._state.history.get(history_id)
        if row is not None:
            self._state.history[history_id] = row.__replace__(
                envelope_json=envelope_json, content_hash=content_hash
            )

    def add_artifact(self, row: LoopHistoryArtifactsRow) -> None:
        if row.history_id not in self._state.history:
            raise ConstraintError("FOREIGN KEY constraint failed")
        self._state.artifacts.append(row)

    def artifacts(self, history_id: str) -> list[ArtifactSummary]:
        rows = sorted(
            (row for row in self._state.artifacts if row.history_id == history_id),
            key=lambda row: row.filename,
        )
        return [
            {
                "id": row.id,
                "filename": row.filename,
                "media_type": row.media_type,
                "content_hash": row.content_hash,
                "size_bytes": row.size_bytes,
                "inclusion": row.inclusion,
            }
            for row in rows
        ]

    def _matching(self, query: HistoryQuery) -> list[LoopHistoryRow]:
        rows = [row for row in self._state.history.values() if _matches(row, query)]
        rows.sort(key=lambda row: row.id)
        rows.sort(key=_moment, reverse=True)
        return rows

    def count(self, query: HistoryQuery, *, fts: bool) -> int:
        del fts
        return len(self._matching(query))

    def page(
        self, query: HistoryQuery, *, fts: bool, limit: int, offset: int
    ) -> list[LoopHistoryRow]:
        del fts
        return self._matching(query)[offset : offset + limit]
