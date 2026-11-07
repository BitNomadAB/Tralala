"""Revisioned Loop documents and human approvals.

Five slots per Loop: ``info`` (human intent), ``analysis_ai``/``analysis`` and
``roadmap_ai``/``roadmap``. Revisions are immutable; current and approved pointers are separate.
Human-facing Markdown is rendered from the validated structure so the human and machine views
cannot drift apart.

``LoopDocumentService`` reaches the board database only through the board unit of work, the
registry only through ``BoardChecks`` and the plan through ``LoopPlanService`` inside the same
unit of work; it takes the clock and the id source as arguments, so every rule here runs in a unit
test without a database. Approvals bind to exact revision ids, a changed input invalidates them,
and approving, requesting changes and resetting are a person's decisions.

The rules live in sibling modules by use case, and this module keeps the service and the public
import path: ``loop_documents_render`` (the Markdown and JSON views of a revision),
``loop_documents_views`` (the JSON the routes return), ``loop_documents_revisions`` (writing a
revision and what it invalidates), ``loop_documents_generated`` (candidates and generation output)
and ``loop_documents_review`` (a person's approval, request for changes or reset).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Forbidden, ValidationFailure, VersionConflict
from ..db.generated.board import LoopDocumentsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..schemas.loops import (
    AnalysisPayload,
    ApprovalRequest,
    CandidateSubmission,
    InfoRevisionWrite,
    PlanPayload,
    QaInstructions,
    ScopeResetRequest,
)
from .lists import BoardChecks
from .loop_documents_generated import (
    store_analysis_candidate,
    store_roadmap_candidate,
    store_run_analysis,
    store_run_roadmap,
)
from .loop_documents_human import store_human_analysis
from .loop_documents_render import (
    content_hash,
    render_analysis,
    render_analysis_technical,
    render_roadmap,
)
from .loop_documents_review import REVIEW_SCOPES, record_review, reset_scope
from .loop_documents_revisions import (
    MAX_DOCUMENT_PAYLOAD,
    invalidate_downstream,
    log_loop_activity,
    write_revision,
)
from .loop_documents_views import (
    ContextDocument,
    DocumentsView,
    GeneratedAnalysis,
    GeneratedRoadmap,
    HumanViewStart,
    LoopContext,
    ResetResult,
    Review,
    RevisionEntry,
    approval_entry,
    document_payload,
    document_view,
    revision_entry,
)
from .loop_plans import LoopPlanService
from .loops import (
    DOCUMENT_KINDS,
    analysis_approved,
    document_slots,
    ensure_writable,
    latest_approvals,
    refresh_stage,
    require_loop,
    roadmap_approved,
    stale_reasons,
)

# A worker may seed or refine Info while the Loop is still speculative — the phase in which a person
# and their agent agree on what to build. Once planning has started, changing the input invalidates
# approvals, so the edit belongs to a signed-in person.
WORKER_INFO_STAGES = frozenset({"draft", "analysis_review"})

# Starts the run in which a board agent writes the analysis for people (actor, board, Loop).
type HumanViewStarter = Callable[[ActorContext, str, str], HumanViewStart]


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopDocumentService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        plans: LoopPlanService,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.plans = plans
        # LoopGenerationService is built after this service, so the composition root sets it.
        self.human_view: HumanViewStarter | None = None
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    # --- reads -----------------------------------------------------------------------------------

    def documents(self, board_id: str, loop_id: str) -> DocumentsView:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            loop = require_loop(repos, loop_id)
            documents = document_slots(repos.documents.current_or_approved(loop_id))
            approvals = latest_approvals(repos.approvals.newest_first(loop_id))
            stale = stale_reasons(documents, approvals)
            return {
                "loop_id": loop_id,
                "loop_version": loop.version,
                "documents": {
                    kind: document_view(
                        loop_id,
                        kind,
                        documents,
                        approvals,
                        stale,
                        repos.documents.page(loop_id, kind, limit=20, offset=0),
                    )
                    for kind in DOCUMENT_KINDS
                },
                "approvals": {
                    scope: approval_entry(approval) for scope, approval in approvals.items()
                },
            }

    def revision_history(
        self, board_id: str, loop_id: str, kind: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[RevisionEntry], int]:
        if kind not in DOCUMENT_KINDS:
            raise ValidationFailure(
                "Unknown document kind",
                details={"allowed": list(DOCUMENT_KINDS)},
            )
        with self.store.reader(board_id) as repos:
            require_loop(repos, loop_id)
            total = repos.documents.count(loop_id, kind)
            records = repos.documents.page(loop_id, kind, limit=limit, offset=offset)
        return [revision_entry(record) for record in records], total

    def context(self, board_id: str, loop_id: str) -> LoopContext:
        """Versioned context for external agents; never contains credentials or other Loops."""
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            context = self.collect_context(repos, require_loop(repos, loop_id))
        context["schemas"] = {
            "analysis": AnalysisPayload.model_json_schema(),
            "roadmap": PlanPayload.model_json_schema(),
            "qa": QaInstructions.model_json_schema(),
        }
        return context

    def collect_context(self, repos: BoardRepositories, loop: LoopsRow) -> LoopContext:
        """Bounded, versioned context for a generation run or an external agent."""
        documents = document_slots(repos.documents.current_or_approved(loop.id))
        context_documents: dict[str, ContextDocument | None] = {}
        for kind in DOCUMENT_KINDS:
            current = documents[kind].current
            context_documents[kind] = (
                {
                    "revision_id": current.id,
                    "revision_number": current.revision_number,
                    "content": current.content,
                    "payload": document_payload(current),
                }
                if current
                else None
            )
        plan = self.plans.plan_view(repos, loop)
        return {
            "loop_id": loop.id,
            "loop_key": loop.key,
            "loop_name": loop.name,
            "goal": loop.goal,
            "stage": loop.stage,
            "documents": context_documents,
            "plan": {
                "plan_id": plan["plan_id"],
                "revision_number": plan["revision_number"],
                "phases": [
                    {
                        "id": phase["id"],
                        "number": phase["number"],
                        "name": phase["name"],
                        "objective": phase["objective"],
                        "state": phase["state"],
                        "tickets": [
                            {
                                "id": ticket["id"],
                                "key": ticket["key"],
                                "title": ticket["title"],
                                "completed_at": ticket["completed_at"],
                                "ready": ticket["ready"],
                                "human_action_required": ticket["human_action_required"],
                            }
                            for ticket in phase["tickets"]
                        ],
                    }
                    for phase in plan["phases"]
                ],
            },
            "labels": [label.name for label in repos.labels.all()],
        }

    # --- writing revisions -----------------------------------------------------------------------

    def _write_revision(
        self,
        repos: BoardRepositories,
        *,
        loop_id: str,
        kind: str,
        content: str,
        payload: Mapping[str, object] | None,
        actor: ActorContext,
        status: str = "ready_for_review",
        sources: Mapping[str, str | None] | None = None,
        generation_run_id: str | None = None,
        provenance: Mapping[str, object] | None = None,
    ) -> LoopDocumentsRow:
        return write_revision(
            repos,
            clock=self._now,
            new_id=self._new_id,
            loop_id=loop_id,
            kind=kind,
            content=content,
            payload=payload,
            actor=actor,
            status=status,
            sources=sources,
            generation_run_id=generation_run_id,
            provenance=provenance,
        )

    def _invalidate_downstream(self, repos: BoardRepositories, loop_id: str, kind: str) -> None:
        invalidate_downstream(repos, loop_id, kind, clock=self._now)

    def save_info(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: InfoRevisionWrite
    ) -> DocumentsView:
        actor.require("loops:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            if not actor.is_user and loop.stage not in WORKER_INFO_STAGES:
                raise Forbidden(
                    "Info is a person's decision once the Loop is being planned",
                    code="human_action_required",
                    details={"stage": loop.stage, "action": "Editing Loop Info"},
                )
            current = repos.documents.current(loop_id, "info")
            if payload.expected_revision_id is not None and (
                current is None or current.id != payload.expected_revision_id
            ):
                raise VersionConflict(
                    "Info changed since it was loaded",
                    code="document_stale",
                    details={
                        "expected_revision_id": payload.expected_revision_id,
                        "current_revision_id": current.id if current else None,
                    },
                )
            document = self._write_revision(
                repos,
                loop_id=loop_id,
                kind="info",
                content=payload.content,
                payload=None,
                actor=actor,
                status="ready_for_review",
                sources={},
                provenance={"note": payload.note},
            )
            self._invalidate_downstream(repos, loop_id, "info")
            self._log(
                repos, actor, "loop.info_revised", loop_id, {"revision": document.revision_number}
            )
            refresh_stage(repos, loop_id, now=self._now())
        return self.documents(board_id, loop_id)

    def submit_candidate(
        self, actor: ActorContext, board_id: str, loop_id: str, payload: CandidateSubmission
    ) -> DocumentsView:
        actor.require("loops:generate")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            if not actor.is_user:
                self._refuse_over_approval(repos, loop, payload.kind)
            self._check_expected(repos, loop_id, payload)
            if payload.kind == "analysis":
                if payload.analysis is None:
                    raise ValidationFailure("An analysis candidate needs an analysis payload")
                self._store_analysis(repos, loop, payload.analysis, actor, payload)
            else:
                if payload.plan is None:
                    raise ValidationFailure("A RoadMap candidate needs a plan payload")
                self._store_roadmap(repos, loop, payload.plan, actor, payload)
            refresh_stage(repos, loop_id, now=self._now())
        # After the commit: the run reads the analysis just stored.
        started = (
            self.after_analysis(actor, board_id, loop_id) if payload.kind == "analysis" else None
        )
        view = self.documents(board_id, loop_id)
        if started is not None:
            view["human_view"] = started
        return view

    def after_analysis(self, actor: ActorContext, board_id: str, loop_id: str) -> HumanViewStart:
        """Have a board agent write the analysis for people from the technical analysis that was
        just stored; without one, the view rendered from the structure stays."""
        if self.human_view is None:
            return {"status": "skipped", "run_id": None, "reason": "not configured"}
        return self.human_view(actor, board_id, loop_id)

    @staticmethod
    def _refuse_over_approval(repos: BoardRepositories, loop: LoopsRow, kind: str) -> None:
        """A token never replaces what a person approved (the logic of WORKER_INFO_STAGES).

        While the scope's approval is current and not stale, a new candidate would silently undo
        it; the person requests changes or resets the scope first, and then the worker may write.
        """
        documents = document_slots(repos.documents.current_or_approved(loop.id))
        approvals = latest_approvals(repos.approvals.newest_first(loop.id))
        stale = stale_reasons(documents, approvals)
        approved = analysis_approved if kind == "analysis" else roadmap_approved
        if approved(documents, approvals, stale):
            what = "analysis" if kind == "analysis" else "RoadMap"
            raise Forbidden(
                f"The {what} is approved; a person requests changes or resets it before an agent "
                "hands in another",
                code="human_action_required",
                details={"stage": loop.stage, "action": f"Replacing an approved {what}"},
            )

    @staticmethod
    def _check_expected(
        repos: BoardRepositories, loop_id: str, payload: CandidateSubmission
    ) -> None:
        """A candidate written from an Info or an analysis that has changed since is refused."""
        expected = (
            ("info", payload.expected_info_revision_id),
            ("analysis_ai", payload.expected_analysis_revision_id),
        )
        for kind, revision_id in expected:
            if revision_id is None:
                continue
            current = repos.documents.current(loop_id, kind)
            if current is None or current.id != revision_id:
                raise VersionConflict(
                    "The candidate was written from a revision that is no longer current",
                    code="document_stale",
                    details={
                        "kind": kind,
                        "expected_revision_id": revision_id,
                        "current_revision_id": current.id if current else None,
                    },
                )

    def _store_analysis(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: AnalysisPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        store_analysis_candidate(
            repos, loop, payload, actor, submission, clock=self._now, new_id=self._new_id
        )

    def _store_roadmap(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: PlanPayload,
        actor: ActorContext,
        submission: CandidateSubmission,
    ) -> None:
        store_roadmap_candidate(
            repos,
            loop,
            payload,
            actor,
            submission,
            plans=self.plans,
            clock=self._now,
            new_id=self._new_id,
        )

    # --- approvals -------------------------------------------------------------------------------

    def review(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ApprovalRequest,
    ) -> Review:
        actor.require_human(
            "Approving an analysis" if scope == "analysis" else "Approving a RoadMap"
        )
        actor.require("loops:review")
        if scope not in {"analysis", "roadmap"}:
            raise ValidationFailure(
                "Unknown review scope", details={"allowed": ["analysis", "roadmap"]}
            )
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            return record_review(
                repos,
                actor,
                loop_id,
                scope,
                payload,
                plans=self.plans,
                clock=self._now,
                new_id=self._new_id,
            )

    def reset(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        scope: str,
        payload: ScopeResetRequest,
    ) -> ResetResult:
        """Clear a scope's documents and drop any approval that stood behind them.

        This is not a rejection: a rejection asks for changes and keeps the text. A reset is the
        person saying "start over", so it works on a draft that was never approved as well as on an
        approved one — the approval row stays as history but is superseded, and both documents of
        the scope are emptied so nothing downstream can execute against text nobody stands behind.
        A reset is a human decision and rejects agent tokens for the same reason an approval does.
        """
        actor.require_human(
            "Resetting the analysis" if scope == "analysis" else "Resetting the RoadMap"
        )
        actor.require("loops:review")
        if scope not in REVIEW_SCOPES:
            raise ValidationFailure(
                "Unknown review scope", details={"allowed": list(REVIEW_SCOPES)}
            )
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            return reset_scope(
                repos, actor, loop_id, scope, payload, clock=self._now, new_id=self._new_id
            )

    # --- generation results ----------------------------------------------------------------------

    def store_generated_analysis(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: AnalysisPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> GeneratedAnalysis:
        return store_run_analysis(
            repos,
            loop,
            payload,
            actor,
            run_id=run_id,
            provenance=provenance,
            clock=self._now,
            new_id=self._new_id,
        )

    def store_human_analysis(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        content: str,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> dict[str, str]:
        return store_human_analysis(
            repos,
            loop,
            content,
            actor,
            run_id=run_id,
            provenance=provenance,
            clock=self._now,
            new_id=self._new_id,
        )

    def store_generated_roadmap(
        self,
        repos: BoardRepositories,
        loop: LoopsRow,
        payload: PlanPayload,
        actor: ActorContext,
        *,
        run_id: str,
        provenance: Mapping[str, object],
    ) -> GeneratedRoadmap:
        return store_run_roadmap(
            repos,
            loop,
            payload,
            actor,
            run_id=run_id,
            provenance=provenance,
            plans=self.plans,
            clock=self._now,
            new_id=self._new_id,
        )

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        loop_id: str,
        changes: Mapping[str, object],
    ) -> None:
        log_loop_activity(
            repos, actor, action, loop_id, changes, clock=self._now, new_id=self._new_id
        )


__all__ = [
    "MAX_DOCUMENT_PAYLOAD",
    "LoopDocumentService",
    "Review",
    "content_hash",
    "render_analysis",
    "render_analysis_technical",
    "render_roadmap",
]
