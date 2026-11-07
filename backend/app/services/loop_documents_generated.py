"""An analysis or a RoadMap an agent wrote: a submitted candidate, or a generation run's output.

Each is stored as a pair of revisions, the technical one holding the validated structure and the
human one: the brief the candidate brought (``loop_documents_human.store_brief``), or else a view
rendered from the structure until somebody writes the brief. A new pair invalidates what was
approved downstream of it. A RoadMap needs a current approved analysis, carries a face for people
on every Ticket (``ticket_face``: a worker is refused with ``422 face_invalid``, a generation was
repaired against the same check before it got here) and registers its plan as a draft. The
functions run inside the unit of work of ``LoopDocumentService``, with its clock and id source.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure, VersionConflict
from ..db.generated.board import LoopsRow
from ..repositories.board import BoardRepositories
from ..schemas.briefs import HumanBrief, RoadmapBrief
from ..schemas.loops import AnalysisPayload, CandidateSubmission, PlanPayload
from .loop_documents_human import MATERIAL_FINDING_CATEGORIES, store_brief
from .loop_documents_render import (
    render_analysis,
    render_analysis_technical,
    render_roadmap,
    render_roadmap_technical,
)
from .loop_documents_revisions import (
    current_id,
    invalidate_downstream,
    log_loop_activity,
    write_revision,
)
from .loop_documents_views import GeneratedAnalysis, GeneratedRoadmap
from .loop_plans import LoopPlanService, validate_plan
from .loops import (
    analysis_approved,
    document_slots,
    latest_approvals,
    refresh_stage,
    stale_reasons,
)
from .ticket_face import plan_face_findings, refuse_face


def validate_analysis(payload: AnalysisPayload) -> None:
    missing = [
        finding.id
        for finding in payload.findings
        if finding.category in MATERIAL_FINDING_CATEGORIES and not finding.plain_language.strip()
    ]
    if missing:
        raise ValidationFailure(
            "Material findings need a plain-language explanation",
            code="validation_failed",
            details={"finding_ids": missing},
        )


def check_roadmap_faces(payload: PlanPayload) -> None:
    """The plan rules first (a broken reference is named as such), then every Ticket's face for
    people: ``422 face_invalid`` naming each Ticket, field and rule. ``register_draft`` checks the
    plan rules again; they are pure and cheap."""
    validate_plan(payload)
    refuse_face(plan_face_findings(payload))


def check_expected_sources(
    repos: BoardRepositories, loop_id: str, submission: CandidateSubmission
) -> None:
    """A candidate written from an Info or an analysis that has changed since is refused."""
    expected = (
        ("info", submission.expected_info_revision_id),
        ("analysis_ai", submission.expected_analysis_revision_id),
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


def store_analysis_candidate(
    repos: BoardRepositories,
    loop: LoopsRow,
    payload: AnalysisPayload,
    actor: ActorContext,
    submission: CandidateSubmission,
    *,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> None:
    validate_analysis(payload)
    info = repos.documents.current(loop.id, "info")
    if info is None and not submission.source_info_revision_id:
        raise Conflict(
            "Analysis needs a current Info revision from a human",
            code="document_stale",
            details={"missing": "info"},
        )
    info_id = info.id if info else submission.source_info_revision_id
    technical = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="analysis_ai",
        content=render_analysis_technical(payload),
        payload=payload.model_dump(),
        actor=actor,
        sources={"info": info_id},
        provenance={"submitted": True, **submission.provenance},
    )
    invalidate_downstream(repos, loop.id, "analysis_ai", clock=clock)
    brief = submission.analysis_brief
    if brief is not None:
        # The brief came with the analysis: it is the human view, checked against the analysis.
        human = store_brief(
            repos,
            loop,
            brief,
            actor,
            provenance={"submitted": True, **submission.provenance},
            clock=clock,
            new_id=new_id,
        )
    else:
        human = write_revision(
            repos,
            clock=clock,
            new_id=new_id,
            loop_id=loop.id,
            kind="analysis",
            content=render_analysis(payload),
            payload=None,
            actor=actor,
            sources={"analysis_ai": technical.id, "info": info_id},
            # Rendered from the structure until somebody writes the brief for people.
            provenance={"submitted": True, "rendered": True, **submission.provenance},
        )
    log_loop_activity(
        repos,
        actor,
        "loop.analysis_candidate",
        loop.id,
        {
            "analysis_ai_revision": technical.revision_number,
            "analysis_revision": human.revision_number,
        },
        clock=clock,
        new_id=new_id,
    )


def store_roadmap_candidate(
    repos: BoardRepositories,
    loop: LoopsRow,
    payload: PlanPayload,
    actor: ActorContext,
    submission: CandidateSubmission,
    *,
    plans: LoopPlanService,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> None:
    documents = document_slots(repos.documents.current_or_approved(loop.id))
    approvals = latest_approvals(repos.approvals.newest_first(loop.id))
    stale = stale_reasons(documents, approvals)
    if not analysis_approved(documents, approvals, stale):
        raise Conflict(
            "RoadMap generation requires a current approved analysis",
            code="approval_required",
            details={"scope": "analysis"},
        )
    check_roadmap_faces(payload)
    draft = plans.register_draft(repos, loop, payload, actor)
    canonical = draft["payload"]
    technical = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="roadmap_ai",
        content=render_roadmap_technical(canonical),
        payload=canonical,
        actor=actor,
        sources={
            "info": current_id(documents, "info"),
            "analysis_ai": current_id(documents, "analysis_ai"),
            "analysis": current_id(documents, "analysis"),
        },
        provenance={"plan_id": draft["plan_id"], **submission.provenance},
    )
    invalidate_downstream(repos, loop.id, "roadmap_ai", clock=clock)
    human = _roadmap_view(
        repos,
        loop,
        canonical_id=technical.id,
        plan_id=draft["plan_id"],
        rendered=render_roadmap(canonical),
        brief=submission.roadmap_brief,
        actor=actor,
        provenance=submission.provenance,
        clock=clock,
        new_id=new_id,
    )
    plans.attach_revisions(
        repos,
        draft["plan_id"],
        roadmap_ai_revision_id=technical.id,
        roadmap_revision_id=human,
    )
    log_loop_activity(
        repos,
        actor,
        "loop.roadmap_candidate",
        loop.id,
        {"plan_id": draft["plan_id"], "phases": len(canonical["phases"])},
        clock=clock,
        new_id=new_id,
    )


def _roadmap_view(
    repos: BoardRepositories,
    loop: LoopsRow,
    *,
    canonical_id: str,
    plan_id: str,
    rendered: str,
    brief: RoadmapBrief | None,
    actor: ActorContext,
    provenance: Mapping[str, object],
    clock: Callable[[], str],
    new_id: Callable[[], str],
    run_id: str | None = None,
) -> str:
    """The RoadMap's human view: the brief, checked against the plan, or the view rendered from
    the plan until somebody writes one. Answers the revision's id."""
    if brief is not None:
        return store_brief(
            repos,
            loop,
            brief,
            actor,
            provenance={"plan_id": plan_id, **provenance},
            clock=clock,
            new_id=new_id,
            run_id=run_id,
        ).id
    return write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="roadmap",
        content=rendered,
        payload=None,
        actor=actor,
        sources={"roadmap_ai": canonical_id},
        generation_run_id=run_id,
        provenance={"plan_id": plan_id, **provenance, "rendered": True},
    ).id


def store_run_analysis(
    repos: BoardRepositories,
    loop: LoopsRow,
    payload: AnalysisPayload,
    actor: ActorContext,
    *,
    run_id: str,
    provenance: Mapping[str, object],
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> GeneratedAnalysis:
    validate_analysis(payload)
    info = repos.documents.current(loop.id, "info")
    if info is None:
        raise Conflict("Analysis needs a current Info revision", code="document_stale")
    technical = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="analysis_ai",
        content=render_analysis_technical(payload),
        payload=payload.model_dump(),
        actor=actor,
        sources={"info": info.id},
        generation_run_id=run_id,
        provenance=provenance,
    )
    human = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="analysis",
        content=render_analysis(payload),
        payload=None,
        actor=actor,
        sources={"analysis_ai": technical.id, "info": info.id},
        generation_run_id=run_id,
        provenance={**provenance, "rendered": True},
    )
    invalidate_downstream(repos, loop.id, "analysis_ai", clock=clock)
    refresh_stage(repos, loop.id, now=clock())
    return {"analysis_ai": technical.id, "analysis": human.id}


def store_run_roadmap(
    repos: BoardRepositories,
    loop: LoopsRow,
    payload: PlanPayload,
    actor: ActorContext,
    *,
    run_id: str,
    provenance: Mapping[str, object],
    plans: LoopPlanService,
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> GeneratedRoadmap:
    documents = document_slots(repos.documents.current_or_approved(loop.id))
    approvals = latest_approvals(repos.approvals.newest_first(loop.id))
    stale = stale_reasons(documents, approvals)
    if not analysis_approved(documents, approvals, stale):
        raise Conflict(
            "RoadMap generation requires a current approved analysis",
            code="approval_required",
        )
    check_roadmap_faces(payload)
    draft = plans.register_draft(repos, loop, payload, actor, drop_unknown_labels=True)
    canonical = draft["payload"]
    technical = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="roadmap_ai",
        content=render_roadmap_technical(canonical),
        payload=canonical,
        actor=actor,
        sources={
            "info": current_id(documents, "info"),
            "analysis_ai": current_id(documents, "analysis_ai"),
            "analysis": current_id(documents, "analysis"),
        },
        generation_run_id=run_id,
        provenance={"plan_id": draft["plan_id"], **provenance},
    )
    human = _roadmap_view(
        repos,
        loop,
        canonical_id=technical.id,
        plan_id=draft["plan_id"],
        rendered=render_roadmap(canonical),
        brief=None,
        actor=actor,
        provenance=provenance,
        clock=clock,
        new_id=new_id,
        run_id=run_id,
    )
    plans.attach_revisions(
        repos,
        draft["plan_id"],
        roadmap_ai_revision_id=technical.id,
        roadmap_revision_id=human,
    )
    invalidate_downstream(repos, loop.id, "roadmap_ai", clock=clock)
    refresh_stage(repos, loop.id, now=clock())
    return {"plan_id": draft["plan_id"], "roadmap_ai": technical.id, "roadmap": human}


def store_run_brief(
    repos: BoardRepositories,
    loop: LoopsRow,
    brief: HumanBrief | RoadmapBrief,
    actor: ActorContext,
    *,
    run_id: str,
    provenance: Mapping[str, object],
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> dict[str, str]:
    """A board agent's brief (an ``analysis_human`` or ``roadmap_human`` run) as the scope's human
    view, from the technical revision the run read: promotion only runs while it is current."""
    human = store_brief(
        repos,
        loop,
        brief,
        actor,
        provenance=provenance,
        clock=clock,
        new_id=new_id,
        run_id=run_id,
    )
    refresh_stage(repos, loop.id, now=clock())
    return {human.kind: human.id}


__all__ = [
    "MATERIAL_FINDING_CATEGORIES",
    "check_expected_sources",
    "store_analysis_candidate",
    "store_roadmap_candidate",
    "store_run_analysis",
    "store_run_brief",
    "store_run_roadmap",
    "validate_analysis",
]
