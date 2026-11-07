"""The brief a person reads, as pure rules: which findings it must name, which ids it may name, what
its visible text may hold, how a RoadMap brief covers the plan, and how a brief is rendered."""

from __future__ import annotations

import pytest
from pydantic import JsonValue

from app.core.errors import ValidationFailure
from app.schemas.briefs import HumanBrief, RoadmapBrief
from app.schemas.loops import AnalysisPayload
from app.services.loop_documents_human import (
    brief_coverage_missing,
    brief_finding_ids,
    brief_text_problems,
    check_analysis_brief,
    check_roadmap_brief,
    plan_outline,
    refuse_problems,
    render_brief,
    text_problems,
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
            {
                "id": "F-11",
                "title": "Provider",
                "category": "decision",
                "technical_detail": "SMTP or an API.",
                "plain_language": "Someone picks the mail provider.",
            },
        ],
        "sources": ["auth.py"],
        "repository_revision": "abc123",
    }
)


def brief(**fields: JsonValue) -> HumanBrief:
    base: dict[str, JsonValue] = {
        "obstacles": [
            {"level": "technical", "text": "Some e-mails bounce.", "finding_ids": ["F-2"]},
            {"level": "legal", "text": "We keep personal data.", "finding_ids": ["F-10"]},
        ],
        "pros": [{"text": "The sign-in can already send mail.", "finding_ids": ["F-1"]}],
        "cons": [{"text": "Bounces need handling.", "finding_ids": ["F-2"]}],
        "decisions": [{"question": "Which mail provider do we use?", "finding_ids": ["F-11"]}],
        "verdict": "yes_with_conditions",
        "verdict_reason": "It works once bounces and retention are handled.",
        "summary": "People confirm their address by e-mail.",
        "recommendation": "Go ahead after the provider is chosen.",
    }
    return HumanBrief.model_validate({**base, **fields})


def test_a_brief_names_the_material_findings_and_the_decisions() -> None:
    assert brief_finding_ids(ANALYSIS) == ["F-2", "F-10", "F-11"]
    assert brief_coverage_missing(brief(), ANALYSIS) == []
    check = check_analysis_brief(brief(), ANALYSIS)
    assert check == {"problems": [], "fields": [], "unknown_ids": [], "missing_ids": []}
    refuse_problems(check)  # nothing to refuse


def test_a_missing_finding_is_refused_with_its_id() -> None:
    partial = brief(decisions=[{"question": "Which mail provider do we use?"}])
    check = check_analysis_brief(partial, ANALYSIS)
    assert check["missing_ids"] == ["F-11"]
    with pytest.raises(ValidationFailure) as refused:
        refuse_problems(check)
    assert refused.value.code == "brief_rejected"
    assert refused.value.details is not None
    assert refused.value.details["missing_ids"] == ["F-11"]
    assert "F-11" in refused.value.message


def test_an_unknown_finding_is_refused() -> None:
    made_up = brief(pros=[{"text": "Cheap.", "finding_ids": ["F-1", "F-99"]}])
    check = check_analysis_brief(made_up, ANALYSIS)
    assert (check["unknown_ids"], check["missing_ids"]) == (["F-99"], [])
    assert check["problems"][0].startswith("finding_ids: the technical analysis has no finding")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Bounces [F01] are lost.", "contains a finding id ([F01])"),
        ("See F01 for why.", "contains a finding id (F01)"),
        ("As F-2 says, mail bounces.", "contains a finding id (F-2)"),
        ("Change app/services/mail.py first.", "contains a file path (app/services/mail.py)"),
        ("Change src\\Mail.tsx first.", "contains a file path (src\\Mail.tsx)"),
        ("Edit `config` first.", "contains code (`config`)"),
        ("```\nsend()\n```", "contains a code fence"),
        ("Ticket 22222222-2222-4222-8222-222222222222.", "contains an id"),
    ],
)
def test_visible_text_with_an_id_a_path_or_code_is_refused(text: str, problem: str) -> None:
    assert any(found.startswith(problem) for found in text_problems(text, ["F-2"]))


@pytest.mark.parametrize(
    "text",
    [
        "People confirm their address by e-mail within 24/7 support hours.",
        "Read the policy at https://example.com/policy.html before deciding.",
        "We need 3 people and 2 weeks; the F1 deadline is in May.",
        "Use the and/or form.",
    ],
)
def test_plain_text_passes(text: str) -> None:
    assert text_problems(text, ["F-2", "3"]) == []


def test_a_bare_finding_id_counts_only_in_brackets() -> None:
    assert text_problems("We need 3 people.", ["3"]) == []
    assert text_problems("We need [3].", ["3"]) != []


def test_each_problem_names_its_field() -> None:
    noisy = brief(
        summary="Mail bounces [F-2].", cons=[{"text": "See app/mail.py.", "finding_ids": ["F-2"]}]
    )
    assert brief_text_problems(noisy, ANALYSIS) == [
        "summary: contains a finding id (F-2); ids belong in finding_ids only",
        "cons[0].text: contains a file path (app/mail.py)",
    ]
    check = check_analysis_brief(noisy, ANALYSIS)
    assert check["fields"] == ["summary", "cons[0].text"]


def test_the_brief_renders_for_people_with_the_verdict_first_and_no_traceability() -> None:
    text = render_brief(brief(), ANALYSIS.model_dump())
    assert text.startswith(
        "# Analysis\n\n**Can it be done?** Yes, with conditions. It works once bounces"
    )
    for heading in ("## What stands in the way", "## For", "## Against"):
        assert heading in text
    assert "- **Legal:** We keep personal data." in text
    assert "## What you need to decide\n\n- Which mail provider do we use?" in text
    assert text.endswith("## Recommendation\n\nGo ahead after the provider is chosen.\n")
    assert "F-2" not in text
    assert "Traceability" not in text
    calm = render_brief(brief(obstacles=[], cons=[]), ANALYSIS.model_dump())
    assert "Nothing was found that stands in the way." in calm
    assert "## Against" not in calm


def test_the_view_rendered_from_the_structure_keeps_its_traceability_block() -> None:
    assert render_analysis(ANALYSIS).endswith("\n---\n\n" + render_traceability(ANALYSIS))


# --- the RoadMap brief ---------------------------------------------------------------------------

P1, P2 = "11111111-1111-4111-8111-111111111111", "11111111-1111-4111-8111-111111111112"
T1, T2 = "22222222-2222-4222-8222-222222222221", "22222222-2222-4222-8222-222222222222"
PLAN: dict[str, JsonValue] = {
    "phases": [
        {
            "id": P1,
            "number": 1,
            "name": "Mail",
            "tickets": [{"id": T1, "key": "AN-1", "title": "Send", "required_actor": "any"}],
        },
        {
            "id": P2,
            "number": 2,
            "name": "Policy",
            "tickets": [{"id": T2, "key": "AN-2", "title": "Sign", "required_actor": "human"}],
        },
    ]
}


def roadmap_brief(**fields: JsonValue) -> RoadmapBrief:
    base: dict[str, JsonValue] = {
        "order": [
            {"phase_id": P2, "what_happens": "The policy is signed.", "done_when": "Signed."},
            {"phase_id": P1, "what_happens": "Mail goes out.", "done_when": "Mail arrives."},
        ],
        "your_part": [
            {"text": "Sign the retention policy.", "phase_ids": [P2], "ticket_ids": [T2]}
        ],
        "could_block": [{"text": "The provider may be late.", "phase_ids": [P1]}],
        "summary": "Two steps: mail, then the policy.",
    }
    return RoadmapBrief.model_validate({**base, **fields})


def test_a_roadmap_brief_covers_every_phase_once_and_every_human_ticket() -> None:
    outline = plan_outline(PLAN)
    assert outline.phases == ((P1, 1, "Mail"), (P2, 2, "Policy"))
    assert check_roadmap_brief(roadmap_brief(), outline)["problems"] == []
    twice = roadmap_brief(
        order=[
            {"phase_id": P1, "what_happens": "Mail.", "done_when": "Sent."},
            {"phase_id": P1, "what_happens": "Again.", "done_when": "Sent."},
        ],
        your_part=[],
    )
    check = check_roadmap_brief(twice, outline)
    assert check["missing_ids"] == [P2, T2]
    assert check["problems"] == [
        f"order: lists a Phase more than once: {P1}",
        f"order: leaves out the Phase(s) {P2}",
        f"your_part: leaves out the Ticket(s) a person must do {T2}",
    ]


def test_a_roadmap_brief_naming_an_unknown_phase_or_ticket_is_refused() -> None:
    other = "33333333-3333-4333-8333-333333333333"
    stray = roadmap_brief(
        your_part=[{"text": "Sign it.", "phase_ids": [other], "ticket_ids": [T2, "t9"]}]
    )
    assert check_roadmap_brief(stray, plan_outline(PLAN))["unknown_ids"] == [other, "t9"]


def test_the_roadmap_brief_renders_the_phases_in_the_plans_order() -> None:
    text = render_brief(roadmap_brief(), PLAN)
    assert text.startswith("# RoadMap\n\nTwo steps: mail, then the policy.\n\n## The order of work")
    assert text.index("### Phase 1 — Mail") < text.index("### Phase 2 — Policy")
    assert "**Done when:** Mail arrives." in text
    assert "## Your part\n\n- Sign the retention policy." in text
    assert "## What could block it\n\n- The provider may be late." in text
    assert P1 not in text
