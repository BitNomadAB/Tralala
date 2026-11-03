"""A completed Loop's history: the sources its immutable snapshot is built from, and the stored
snapshots themselves, as ``LoopHistoryService`` finalizes, imports, reads and searches them."""

from __future__ import annotations

from typing import Protocol, TypedDict

from ..db.generated.board import (
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


class ChecklistLine(TypedDict):
    """One checklist item of a Ticket, or a checklist without items (``text`` is then null)."""

    card_id: str
    title: str
    text: str | None
    completed: int | None


class ArtifactSummary(TypedDict):
    """A stored evidence file without its bytes."""

    id: str
    filename: str
    media_type: str
    content_hash: str
    size_bytes: int
    inclusion: str


class NativeHistory(TypedDict):
    """A completed Loop's snapshot, as finalization stores it."""

    id: str
    history_schema_version: int
    board_id: str
    loop_id: str
    loop_key: str
    loop_name: str
    qa_status: str
    envelope_json: str
    search_text: str
    content_hash: str
    now: str


class ImportedHistory(TypedDict):
    """Legacy material, stored as a reference and never as a Loop."""

    id: str
    history_schema_version: int
    board_id: str
    loop_name: str
    qa_status: str
    envelope_json: str
    search_text: str
    content_hash: str
    now: str
    imported_by_actor_id: str
    source_project: str | None
    source_reference: str | None
    source_format: str | None
    source_version: str | None
    validation_warnings_json: str


class HistoryQuery(TypedDict, total=False):
    """The history search's filters; a key that is present filters."""

    match: str
    q: str
    source_kind: str
    loop_key: str
    loop_key_like: str
    qa_status: str
    date_from: str
    date_to: str


class LoopArchiveRepository(Protocol):
    """Everything a completed Loop's snapshot records, each in the order the snapshot lists it."""

    def documents(self, loop_id: str) -> list[LoopDocumentsRow]:
        """Every document revision, by kind and revision number."""
        ...

    def approvals(self, loop_id: str) -> list[LoopApprovalsRow]: ...

    def plans(self, loop_id: str) -> list[LoopPlansRow]: ...

    def phases(self, loop_id: str) -> list[LoopPhasesRow]: ...

    def plan_items(self, loop_id: str) -> list[LoopPlanItemsRow]: ...

    def dependencies(self, loop_id: str) -> list[LoopDependenciesRow]: ...

    def tickets(self, loop_id: str) -> list[CardsRow]:
        """The Loop's Tickets by key, then creation time."""
        ...

    def comments(self, loop_id: str) -> list[CommentsRow]: ...

    def checklist_lines(self, loop_id: str) -> list[ChecklistLine]: ...

    def qa_cycles(self, loop_id: str) -> list[LoopQaCyclesRow]: ...

    def qa_results(self, loop_id: str) -> list[LoopQaResultsRow]: ...

    def generation_runs(self, loop_id: str) -> list[LoopGenerationRunsRow]: ...

    def activity(self, loop_id: str) -> list[ActivityLogRow]:
        """The activity recorded on the Loop itself, oldest first."""
        ...

    def attachments(self, loop_id: str) -> list[AttachmentsRow]:
        """The live files on the Loop's Tickets, oldest first."""
        ...


class LoopHistoryRepository(Protocol):
    def get(self, history_id: str) -> LoopHistoryRow | None: ...

    def native_for(self, board_id: str, loop_id: str) -> LoopHistoryRow | None:
        """The snapshot finalization wrote for the Loop, if it has one."""
        ...

    def add_native(self, entry: NativeHistory) -> None: ...

    def add_imported(self, entry: ImportedHistory) -> None: ...

    def seal(self, history_id: str, *, envelope_json: str, content_hash: str) -> None:
        """Store the snapshot as it is final, with the hash of exactly that text."""
        ...

    def add_artifact(self, row: LoopHistoryArtifactsRow) -> None: ...

    def artifacts(self, history_id: str) -> list[ArtifactSummary]:
        """The snapshot's evidence files without their bytes, by file name."""
        ...

    def count(self, query: HistoryQuery, *, fts: bool) -> int: ...

    def page(
        self, query: HistoryQuery, *, fts: bool, limit: int, offset: int
    ) -> list[LoopHistoryRow]:
        """Matching snapshots, newest first."""
        ...
