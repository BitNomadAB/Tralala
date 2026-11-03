"""The analysis a person reads, written by a board agent from the technical analysis.

A person and a model read differently. The technical analysis (``analysis_ai``) is structure for
engineers and models; the human view (``analysis``) is prose for a project manager. Until a board
agent writes that prose, the human view is rendered from the structure (``render_analysis``) and
says so in its provenance (``rendered``). The agent's text replaces it only when it covers every
material finding by id; the server, not the model, appends the traceability block, so the view
always leads back to the exact findings it explains. Everything here is pure except
``store_human_analysis``, which writes the revision inside the caller's unit of work.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..core.errors import Conflict, ValidationFailure
from ..db.generated.board import LoopsRow
from ..repositories.board import BoardRepositories
from ..schemas.loops import AnalysisPayload
from .loop_documents_generated import MATERIAL_FINDING_CATEGORIES
from .loop_documents_render import render_traceability
from .loop_documents_revisions import MAX_DOCUMENT_PAYLOAD, log_loop_activity, write_revision

# A heading the model wrote for the traceability block anyway, and everything after it.
_TRACEABILITY = re.compile(
    r"^#{1,6}\s*Traceability\b.*\Z", re.IGNORECASE | re.MULTILINE | re.DOTALL
)
_FENCE = re.compile(r"\A```[\w-]*\s*\n(?P<body>.*)\n```\s*\Z", re.DOTALL)
# Horizontal rules left at the end once that section is gone.
_TRAILING_RULES = re.compile(r"(?:\n\s*(?:-{3,}|\*{3,}|_{3,})\s*)+\Z")


def material_ids(payload: AnalysisPayload) -> list[str]:
    """The findings a person must be told about, in the analysis's order."""
    return [
        finding.id
        for finding in payload.findings
        if finding.category in MATERIAL_FINDING_CATEGORIES
    ]


def _mentions(text: str, finding_id: str) -> bool:
    """The id as a whole word: ``F-1`` is not found inside ``F-10`` or ``XF-1``."""
    pattern = rf"(?<![\w-]){re.escape(finding_id)}(?![\w-])"
    return re.search(pattern, text) is not None


def coverage_missing(text: str, payload: AnalysisPayload) -> list[str]:
    """The material findings the text never names by id."""
    return [finding_id for finding_id in material_ids(payload) if not _mentions(text, finding_id)]


def written_text(answer: str) -> str:
    """The model's prose: one surrounding code fence and a traceability section it wrote anyway
    are removed, since the server adds the traceability block itself."""
    text = answer.strip()
    fenced = _FENCE.match(text)
    if fenced is not None:
        text = fenced.group("body").strip()
    text = _TRACEABILITY.sub("", text).strip()
    return _TRAILING_RULES.sub("", "\n" + text).strip()


def compose_human_view(text: str, payload: AnalysisPayload) -> str:
    """The agent's text, a rule, and the traceability block rendered from the structure."""
    return f"{written_text(text)}\n\n---\n\n{render_traceability(payload)}"


def store_human_analysis(
    repos: BoardRepositories,
    loop: LoopsRow,
    content: str,
    actor: ActorContext,
    *,
    run_id: str,
    provenance: Mapping[str, object],
    clock: Callable[[], str],
    new_id: Callable[[], str],
) -> dict[str, str]:
    """The written view as the Loop's current ``analysis`` revision, from the current technical
    analysis and Info; the run is only promoted while those are the ones it read."""
    technical = repos.documents.current(loop.id, "analysis_ai")
    if technical is None or not technical.payload_json:
        raise Conflict(
            "There is no technical analysis to write for people",
            code="document_empty",
            details={"kind": "analysis_ai"},
        )
    if len(content) > MAX_DOCUMENT_PAYLOAD:
        raise ValidationFailure(
            "The analysis written for people exceeds the configured size limit",
            code="payload_too_large",
            details={"limit": MAX_DOCUMENT_PAYLOAD},
        )
    info = repos.documents.current(loop.id, "info")
    human = write_revision(
        repos,
        clock=clock,
        new_id=new_id,
        loop_id=loop.id,
        kind="analysis",
        content=content,
        payload=None,
        actor=actor,
        sources={"analysis_ai": technical.id, "info": info.id if info else None},
        generation_run_id=run_id,
        provenance={**provenance, "written": True},
    )
    log_loop_activity(
        repos,
        actor,
        "loop.analysis_written_for_people",
        loop.id,
        {
            "analysis_revision": human.revision_number,
            "analysis_ai_revision": technical.revision_number,
        },
        clock=clock,
        new_id=new_id,
    )
    return {"analysis": human.id}


__all__ = [
    "compose_human_view",
    "coverage_missing",
    "material_ids",
    "store_human_analysis",
    "written_text",
]
