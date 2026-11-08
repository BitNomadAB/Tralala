"""How a generation steers the model to the analysis brief's sign, and how it measures it.

The analysis brief's prompt states the sign once with one example question (``BRIEF_SIGN_RULE``,
that purpose only). A brief that breaks it is sent back through the repair round every generation
shares (``repair_round``): its messages first, one per line, the sign's before the content rules,
then what to do; every problem of the sign is an ``analysis_brief_repair`` log line, and the run's
tree ends its checking with "Repairs: N (face: 0, brief: M)". A second broken brief fails the run
with ``brief_invalid`` (``give_up``), and the view rendered from the structure stays. Everything
runs on the fakes, the provider scripted.
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import JsonValue

from app.services.loop_documents_human_limits import SIGN_QUESTION_EXAMPLE
from app.services.loop_generation_ask import BRIEF_REPAIR
from app.services.loop_generation_prompts import BRIEF_SIGN_RULE, PURPOSE_PROMPTS
from app.services.loop_generation_report import repairs_line
from app.services.loop_generation_trace import counts_of, parse_steps
from tests.unit.log_lines import events
from tests.unit.test_loop_generation_service import (
    LOOP,
    World,
    answer,
    brief,
    human_view,
    make,
    start,
    with_technical_analysis,
)

WRITTEN = json.dumps(brief())
NO_SIZE = json.dumps({**brief(), "size": None})
LONG_LINE = json.dumps({**brief(), "verdict_line": " ".join(["word"] * 25), "size": None})
REPAIR_EVENT = "analysis_brief_repair"
SIZE_MISSING = (
    "Brief, size: missing. Say how big the work is: small, medium or large, and why in one "
    "sentence."
)


def steps_of(w: World) -> list[dict[str, JsonValue]]:
    return [step for step in parse_steps(w.run().trace_json) if isinstance(step, dict)]


def test_the_analysis_brief_prompt_states_the_sign_once_with_one_question() -> None:
    prompt = PURPOSE_PROMPTS["analysis_human"]
    assert prompt.count(BRIEF_SIGN_RULE) == 1
    assert prompt.count(SIGN_QUESTION_EXAMPLE) == 1
    for limit in ("at most 20 words", "at most 3 obstacles", "at most 5 decisions", "140"):
        assert limit in BRIEF_SIGN_RULE
    assert "small, medium or large" in BRIEF_SIGN_RULE
    assert BRIEF_SIGN_RULE not in PURPOSE_PROMPTS["roadmap_human"]


def test_a_brief_without_its_size_is_repaired_with_the_sign_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = make(answers=[answer(NO_SIZE), answer(WRITTEN)])
    with_technical_analysis(w)
    with caplog.at_level(logging.INFO, logger="tralala.loop_generation"):
        start(w, "analysis_human")
    assert w.run().status == "completed"
    content = str(w.provider.calls[1].messages[2]["content"])
    assert content == f"{SIZE_MISSING}\n{BRIEF_REPAIR}"
    (repair,) = [step for step in steps_of(w) if step["kind"] == "repair"]
    assert repair["brief"] == 1
    assert str(repair["text"]).startswith(f"The answer broke a rule: {SIZE_MISSING}")
    checking = [step["text"] for step in steps_of(w) if step["stage"] == "checking"]
    assert checking[-1] == "Repairs: 1 (face: 0, brief: 1)"
    logged = [event for event in events(caplog.records) if event["event"] == REPAIR_EVENT]
    assert logged == [
        {
            "event": "analysis_brief_repair",
            "loop_id": LOOP,
            "run_id": "id-1",
            "attempt": 1,
            "field": "size",
            "rule": "missing",
        }
    ]
    stored = json.loads(human_view(w).payload_json or "{}")
    assert stored["size"] == {"kind": "small", "text": "One change to sign-in and one new e-mail."}


def test_a_brief_that_still_breaks_the_sign_fails_brief_invalid_and_the_view_stays(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = make(answers=[answer(LONG_LINE), answer(LONG_LINE)])
    with_technical_analysis(w)
    with caplog.at_level(logging.INFO, logger="tralala.loop_generation"):
        start(w, "analysis_human")
    run = w.run()
    assert (run.status, run.error_code) == ("failed", "brief_invalid")
    problems = json.loads(run.output_json)["error_details"]["problems"]
    assert problems == ["Brief, verdict_line: 25 words, at most 20.", SIZE_MISSING]
    logged = [event for event in events(caplog.records) if event["event"] == REPAIR_EVENT]
    assert [(event["attempt"], event["field"], event["rule"]) for event in logged] == [
        (1, "verdict_line", "words"),
        (1, "size", "missing"),
        (2, "verdict_line", "words"),
        (2, "size", "missing"),
    ]
    errors = [step["text"] for step in steps_of(w) if step["kind"] == "error"]
    assert str(errors[0]).startswith("The answer still broke a rule after 1 repair: Brief,")
    assert human_view(w).id == "an-1"
    finished = [
        event for event in events(caplog.records) if event["event"] == "generation_run_finished"
    ]
    assert (finished[0]["repairs"], finished[0]["brief_repairs"]) == (1, 1)


def test_the_report_counts_the_brief_repairs_apart_only_when_there_were_some() -> None:
    steps: list[JsonValue] = [
        {"stage": "checking", "kind": "repair", "text": "a", "at": "t", "brief": 2},
        {"stage": "checking", "kind": "repair", "text": "b", "at": "t"},
    ]
    counts = counts_of(steps)
    assert (counts["repairs"], counts["face_repairs"], counts["brief_repairs"]) == (2, 0, 1)
    assert repairs_line(counts) == "Repairs: 2 (face: 0, brief: 1)"
    assert repairs_line(counts_of(steps[1:])) == "Repairs: 1 (face: 0)"
