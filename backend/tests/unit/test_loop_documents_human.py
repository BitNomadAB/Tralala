"""The analysis written for people, as pure rules: which findings it must name, what of the model's
answer is kept, and how the server's traceability block is put under it."""

from __future__ import annotations

from app.schemas.loops import AnalysisPayload
from app.services.loop_documents_human import (
    compose_human_view,
    coverage_missing,
    material_ids,
    written_text,
)
from app.services.loop_documents_render import render_analysis, render_traceability

ANALYSIS = AnalysisPayload.model_validate(
    {
        "outcome": "Verify addresses",
        "findings": [
            {
                "id": "F-1",
                "title": "Reuse sign-in",
                "category": "reuse",
                "technical_detail": "auth.py sends mail.",
                "plain_language": "Sign-in can send it.",
            },
            {
                "id": "F-2",
                "title": "Bounces",
                "category": "risk",
                "technical_detail": "No bounce handling.",
                "plain_language": "Some mail is lost.",
            },
            {
                "id": "F-10",
                "title": "Retention",
                "category": "legal",
                "technical_detail": "Addresses are personal data.",
                "plain_language": "We must say how long we keep them.",
            },
        ],
        "sources": ["auth.py"],
        "repository_revision": "abc123",
    }
)


def test_the_material_findings_are_the_ones_a_person_must_be_told_about() -> None:
    assert material_ids(ANALYSIS) == ["F-2", "F-10"]


def test_a_finding_counts_as_covered_only_when_its_id_stands_as_a_word() -> None:
    assert coverage_missing("Mail can bounce [F-2]. Retention [F-10].", ANALYSIS) == []
    # F-1 inside F-10 is not F-1, and a reuse finding need not be named at all.
    assert coverage_missing("Only [F-10] here.", ANALYSIS) == ["F-2"]
    assert coverage_missing("XF-2 and F-20 and F-2x are other ids.", ANALYSIS) == ["F-2", "F-10"]
    assert coverage_missing("F-2, then (F-10)", ANALYSIS) == []


def test_the_models_fence_and_traceability_section_are_dropped() -> None:
    fenced = "```markdown\n# For people\n\nBounces [F-2].\n```"
    assert written_text(fenced) == "# For people\n\nBounces [F-2]."
    own = "# For people\n\nBounces [F-2].\n\n---\n\n## Traceability\n\n- F-2: made up"
    assert written_text(own) == "# For people\n\nBounces [F-2]."
    assert written_text("  Plain text.  ") == "Plain text."


def test_the_view_is_the_text_a_rule_and_the_servers_traceability_block() -> None:
    view = compose_human_view("Bounces [F-2], retention [F-10].\n## traceability\nnope", ANALYSIS)
    assert view == (
        "Bounces [F-2], retention [F-10].\n\n---\n\n" + render_traceability(ANALYSIS)
    )
    assert "`F-10` (legal) Retention: Addresses are personal data." in view
    assert "Baseline revision: `abc123`" in view
    assert "nope" not in view


def test_the_rendered_view_ends_with_the_same_traceability_block() -> None:
    assert render_analysis(ANALYSIS).endswith("\n---\n\n" + render_traceability(ANALYSIS))
