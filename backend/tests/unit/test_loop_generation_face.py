"""How a RoadMap generation steers the model to the face for people, and how it measures it.

The prompt states the rule once with one good and one bad step (``FACE_RULE``, the RoadMap purpose
only) and the schema lists the face last in every Ticket. A RoadMap run shows up to two faces the
owner approved, read from the plan items of the board's newest approved RoadMap and kept in the
run's input. A face that breaks its template is sent back with its messages first, one per line;
every round is a repair step whose text is the first problem, every problem a
``roadmap_face_repair`` log line, and the run's tree ends its checking with "Repairs: N (face: M)".
A worker reads the same good and bad step in ``write_roadmap``'s description and in ``/llms.txt``.
Everything runs on the fakes, the provider scripted.
"""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import JsonValue

from app.api.mcp import render_bootstrap
from app.core.config import Settings
from app.core.errors import ValidationFailure
from app.db.generated.board import LoopPlanItemsRow
from app.schemas.loops import PlanTicket
from app.services.agent_tools import tool_catalog
from app.services.loop_generation_ask import FACE_REPAIR, MAX_REPAIRS, repair_step
from app.services.loop_generation_prompts import (
    FACE_EXAMPLES_HEADING,
    FACE_RULE,
    PURPOSE_PROMPTS,
    compose_system_prompt,
    face_examples,
    face_examples_block,
    parse_output,
    response_schema_for,
    user_message,
)
from app.services.loop_generation_report import repairs_line
from app.services.loop_generation_trace import counts_of, parse_steps
from app.services.ticket_face import (
    FACE_STEP_BAD,
    FACE_STEP_GOOD,
    FaceRefusal,
    face_findings,
    face_to_text,
    make_face,
)
from tests.unit.faces import FACE
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    approval_row,
    board_unit_of_work,
    loop_row,
    plan_item_row,
    plan_row,
)
from tests.unit.log_lines import events
from tests.unit.test_loop_generation_service import (
    LOOP,
    OTHER,
    PHASE,
    TICKET,
    TOO_MANY_STEPS,
    UNKNOWN_PHASE,
    World,
    answer,
    approve_analysis,
    long_steps_roadmap,
    make,
    roadmap,
    start,
)

FACE_FIELDS_LAST = ["summary", "why", "if_skipped", "pros", "cons", "steps"]


# --- the rule ------------------------------------------------------------------------------------


def test_the_roadmap_prompt_states_the_face_rule_and_the_analysis_prompt_does_not() -> None:
    assert FACE_RULE in PURPOSE_PROMPTS["roadmap"]
    assert FACE_RULE in compose_system_prompt("roadmap", "You are the planner.")
    for purpose in ("analysis", "analysis_human", "roadmap_human", "qa"):
        assert FACE_RULE not in compose_system_prompt(purpose, "")
        assert FACE_STEP_GOOD not in PURPOSE_PROMPTS[purpose]
    # The rule replaces the summary's old wording; it is stated once.
    assert "one or two plain sentences" not in PURPOSE_PROMPTS["roadmap"]
    assert PURPOSE_PROMPTS["roadmap"].count("Write the plan first.") == 1


def test_the_face_rule_reads_as_the_ticket_gives_it() -> None:
    assert FACE_RULE.startswith(
        "Write the plan first. Then, last in every Ticket, write its face for the person who will "
        "own it: a summary of at most 20 words"
    )
    for part in (
        "at most 3 sentences each",
        "up to 3 points for (pros) and 3 against (cons)",
        "1 to 5 steps (steps)",
        "A step names what changes for the person: a button, a text, a list, a column. Never "
        "where in the code.",
        "No file path, code symbol, code fence or id in these fields; those belong in the "
        "acceptance criteria and the evidence.",
        "If a Ticket needs more than 5 steps, split it into two Tickets.",
    ):
        assert part in FACE_RULE
    assert FACE_RULE.endswith(f'Step, good: "{FACE_STEP_GOOD}" Step, bad: "{FACE_STEP_BAD}"')


def test_the_good_step_keeps_the_template_and_the_bad_one_breaks_it() -> None:
    def rules(step: str) -> list[tuple[str, str]]:
        found = face_findings("T", "Answer the open questions.", "W.", "S.", [], [], [step])
        return [(problem.field, problem.rule) for problem in found]

    assert rules(FACE_STEP_GOOD) == []
    assert rules(FACE_STEP_BAD) == [("steps[0]", "file_path"), ("steps[0]", "code_symbol")]


def test_the_schema_lists_each_tickets_face_last_in_writing_order() -> None:
    schema = response_schema_for("roadmap")["schema"]
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    ticket = definitions["PlanTicket"]
    assert isinstance(ticket, dict)
    properties = ticket["properties"]
    assert isinstance(properties, dict)
    assert list(properties)[-6:] == FACE_FIELDS_LAST
    assert list(PlanTicket.model_fields)[-6:] == FACE_FIELDS_LAST


def test_a_plan_stored_with_the_summary_before_the_objective_still_parses() -> None:
    stored: dict[str, JsonValue] = {
        "id": TICKET,
        "title": "Add columns",
        "summary": FACE["summary"],
        "objective": "Store it",
        **{name: value for name, value in FACE.items() if name != "summary"},
    }
    ticket = PlanTicket.model_validate(stored)
    assert (ticket.summary, ticket.objective) == (FACE["summary"], "Store it")


# --- examples the owner approved -----------------------------------------------------------------


def face_text(step: str) -> str:
    return face_to_text(
        make_face("It is needed.", "Work waits.", ["Faster"], [], [step, "Then save it"])
    )


def item(
    item_id: str,
    plan_id: str,
    *,
    loop_id: str = OTHER,
    phase: int = 1,
    sequence: int = 1,
    face: str = "",
) -> LoopPlanItemsRow:
    return plan_item_row(item_id, loop_id, plan_id, f"phase-{phase}").__replace__(
        phase_number=phase,
        ticket_sequence=sequence,
        key=f"K-{item_id}",
        summary=f"Summary of {item_id}.",
        face=face,
    )


def approved_plan(state: BoardState, plan_id: str, loop_id: str, approval_id: str, at: str) -> None:
    state.approvals.append(approval_row(approval_id, loop_id, "roadmap", created_at=at))
    state.plans[plan_id] = plan_row(plan_id, loop_id).__replace__(approval_id=approval_id)


def board_with_approvals(state: BoardState) -> None:
    """Two approved RoadMaps of another Loop than the one a run plans, and a newer draft. The
    newest approval's plan has a Ticket without a face and two with one, stored out of plan order;
    the older approval's and the draft's faced Tickets come after them, or never."""
    approved_plan(state, "plan-old", OTHER, "ap-old", "2026-11-01T09:00:00Z")
    approved_plan(state, "plan-new", OTHER, "ap-new", "2026-11-02T09:00:00Z")
    state.plans["plan-draft"] = plan_row("plan-draft", OTHER, status="draft")
    for row in (
        item("old", "plan-old", face=face_text("Show the old list")),
        item("late", "plan-new", phase=2, sequence=1, face=face_text("Show the late column")),
        item("bare", "plan-new", phase=1, sequence=1),
        item("early", "plan-new", phase=1, sequence=2, face=face_text("Show the early button")),
        item("draft", "plan-draft", face=face_text("Show the draft text")),
    ):
        state.plan_items[row.id] = row


def test_the_plan_items_answer_the_newest_approved_faces_in_plan_order() -> None:
    state = BoardState()
    state.loops = {LOOP: loop_row(LOOP), OTHER: loop_row(OTHER).__replace__(key="L-2")}
    board_with_approvals(state)
    with board_unit_of_work(state).reader(BOARD_ID) as repos:
        assert [row.id for row in repos.plan_items.approved_faces(2)] == ["early", "late"]
        # Past the newest approval, the next one follows in its own plan order.
        assert [row.id for row in repos.plan_items.approved_faces(5)] == ["early", "late", "old"]
        # A rejected review publishes nothing, so its plan is no example.
        state.approvals = [row.__replace__(decision="changes_requested") for row in state.approvals]
        assert repos.plan_items.approved_faces(2) == []


def test_the_example_block_shows_each_face_as_its_six_fields() -> None:
    rows = [
        item("a", "p", face=face_text("Show a button")),
        item("b", "p", face="not json"),
        item("c", "p", face=face_text("Show a list")),
        item("d", "p", face=face_text("Show a column")),
    ]
    examples = face_examples(rows)
    assert [example["steps"][0] for example in examples] == ["Show a button", "Show a list"]
    block = face_examples_block(json.loads(json.dumps(examples)))
    assert block == "\n".join(
        [
            FACE_EXAMPLES_HEADING,
            "Example 1",
            "Summary: Summary of a.",
            "Why: It is needed.",
            "If we skip it: Work waits.",
            "For:",
            "- Faster",
            "Against: (none)",
            "Steps:",
            "1. Show a button",
            "2. Then save it",
            "Example 2",
            "Summary: Summary of c.",
            "Why: It is needed.",
            "If we skip it: Work waits.",
            "For:",
            "- Faster",
            "Against: (none)",
            "Steps:",
            "1. Show a list",
            "2. Then save it",
        ]
    )
    assert face_examples_block([]) is None
    assert face_examples_block(None) is None


def test_the_request_shows_the_examples_before_the_context() -> None:
    examples: list[JsonValue] = json.loads(
        json.dumps(face_examples([item("a", "p", face=face_text("Go"))]))
    )
    captured: dict[str, JsonValue] = {
        "purpose": "roadmap",
        "context": {"loop_name": "Loop", "loop_key": "L-1"},
        "face_examples": examples,
    }
    message = user_message(captured)
    assert message.index(FACE_EXAMPLES_HEADING) < message.index("Context (JSON):")
    assert FACE_EXAMPLES_HEADING not in user_message({**captured, "face_examples": []})


def test_a_roadmap_run_shows_the_two_newest_approved_faces_and_keeps_them() -> None:
    w = make(answers=[answer(json.dumps(roadmap()))])
    approve_analysis(w)
    board_with_approvals(w.state)
    start(w, "roadmap")
    request = w.provider.calls[0].messages[0]["content"]
    block = request.split(FACE_EXAMPLES_HEADING, 1)[1].split("Context (JSON):", 1)[0]
    assert block.index("Show the early button") < block.index("Show the late column")
    for left_out in ("Summary of bare.", "Show the old list", "Show the draft text"):
        assert left_out not in request
    # The run's input keeps what the model was shown, so its history says it.
    kept = json.loads(w.run().input_json)["face_examples"]
    assert [example["summary"] for example in kept] == ["Summary of early.", "Summary of late."]
    assert w.run().status == "completed"


def test_a_board_without_an_approved_face_shows_no_example_block() -> None:
    w = make(answers=[answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    assert FACE_EXAMPLES_HEADING not in w.provider.calls[0].messages[0]["content"]
    assert json.loads(w.run().input_json)["face_examples"] == []


def test_an_analysis_run_captures_no_examples() -> None:
    w = make()
    board_with_approvals(w.state)
    start(w, "analysis")
    assert "face_examples" not in json.loads(w.run().input_json)
    assert FACE_EXAMPLES_HEADING not in w.provider.calls[0].messages[0]["content"]


# --- repairs -------------------------------------------------------------------------------------


def steps_of(w: World) -> list[dict[str, JsonValue]]:
    return [step for step in parse_steps(w.run().trace_json) if isinstance(step, dict)]


def test_a_face_repair_starts_with_the_face_messages_and_the_tree_shows_the_first() -> None:
    broken = json.dumps(long_steps_roadmap())
    w = make(answers=[answer(broken), answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    content = w.provider.calls[1].messages[2]["content"]
    assert content.startswith(f"{TOO_MANY_STEPS}\n")
    assert content.endswith(FACE_REPAIR)
    (repair,) = [step for step in steps_of(w) if step["kind"] == "repair"]
    assert repair["text"] == repair_step(TOO_MANY_STEPS)
    assert repair["face"] == 1
    checking = [step["text"] for step in steps_of(w) if step["stage"] == "checking"]
    assert checking[-1] == "Repairs: 1 (face: 1)"
    assert w.run().status == "completed"


def long_steps_waiting_for(phase_id: str) -> dict[str, JsonValue]:
    """The RoadMap of ``long_steps_roadmap`` whose Phase also waits for ``phase_id``."""
    steps: list[JsonValue] = [f"Step {n}" for n in range(7)]
    ticket: dict[str, JsonValue] = {**FACE, "id": TICKET, "title": "Add columns", "steps": steps}
    phase: dict[str, JsonValue] = {
        "id": PHASE,
        "number": 1,
        "name": "Database",
        "prerequisite_phase_ids": [phase_id],
        "tickets": [ticket],
    }
    return {"summary": "One phase", "phases": [phase]}


def test_the_face_comes_before_a_plan_rule_the_same_answer_breaks() -> None:
    both = long_steps_waiting_for(UNKNOWN_PHASE)
    w = make(answers=[answer(json.dumps(both)), answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    lines = w.provider.calls[1].messages[2]["content"].splitlines()
    assert lines[0] == TOO_MANY_STEPS
    assert lines[1].startswith("Phase dependency references an unknown Phase")
    assert f'"missing": "{UNKNOWN_PHASE}"' in lines[1]
    assert lines[2] == FACE_REPAIR
    (repair,) = [step for step in steps_of(w) if step["kind"] == "repair"]
    assert repair["text"] == repair_step(TOO_MANY_STEPS, 1)


def test_without_a_face_problem_a_plan_rule_is_repaired_as_before() -> None:
    w = make(answers=[answer(json.dumps(roadmap([UNKNOWN_PHASE]))), answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    content = w.provider.calls[1].messages[2]["content"]
    assert content.startswith("That response did not validate.")
    (repair,) = [step for step in steps_of(w) if step["kind"] == "repair"]
    assert "face" not in repair
    checking = [step["text"] for step in steps_of(w) if step["stage"] == "checking"]
    assert checking[-1] == "Repairs: 1 (face: 0)"


def test_every_face_problem_of_every_round_is_logged_and_the_run_fails_face_invalid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    answers = [answer(json.dumps(long_steps_roadmap()))] * (MAX_REPAIRS + 1)
    w = make(answers=answers)
    approve_analysis(w)
    with caplog.at_level(logging.INFO, logger="tralala.loop_generation"):
        start(w, "roadmap")
    repairs = [event for event in events(caplog.records) if event["event"] == "roadmap_face_repair"]
    where = {"loop_id": LOOP, "run_id": "id-1", "ticket_id": TICKET}
    assert repairs == [
        {
            "event": "roadmap_face_repair",
            **where,
            "attempt": n,
            "field": "steps",
            "rule": "too_many",
        }
        for n in range(1, MAX_REPAIRS + 2)
    ]
    run = w.run()
    assert (run.status, run.error_code) == ("failed", "face_invalid")
    details = json.loads(run.output_json)["error_details"]
    assert details["errors"] == [TOO_MANY_STEPS]
    checking = [step["text"] for step in steps_of(w) if step["stage"] == "checking"]
    assert checking[-1] == f"Repairs: {MAX_REPAIRS} (face: {MAX_REPAIRS})"
    finished = [
        event for event in events(caplog.records) if event["event"] == "generation_run_finished"
    ]
    assert (finished[0]["repairs"], finished[0]["face_repairs"]) == (MAX_REPAIRS, MAX_REPAIRS)


def test_a_run_without_a_repair_says_nothing_about_repairs() -> None:
    w = make(answers=[answer(json.dumps(roadmap()))])
    approve_analysis(w)
    start(w, "roadmap")
    assert not any(str(step["text"]).startswith("Repairs:") for step in steps_of(w))


def test_parse_output_names_the_face_first_and_the_other_problems_after_it() -> None:
    with pytest.raises(FaceRefusal) as refused:
        parse_output("roadmap", json.dumps(long_steps_waiting_for(PHASE)), labels=())
    error = refused.value
    assert error.messages()[0] == TOO_MANY_STEPS
    assert error.messages()[1].startswith("A Phase cannot depend on itself")
    assert error.details is not None and error.details["other_errors"] == error.messages()[1:]
    # Without a face problem the plan rule raises on its own, as before.
    with pytest.raises(ValidationFailure) as rule:
        parse_output("roadmap", json.dumps(roadmap([PHASE])), labels=())
    assert not isinstance(rule.value, FaceRefusal)
    assert rule.value.message == "A Phase cannot depend on itself"


# --- the report ----------------------------------------------------------------------------------


def test_the_report_counts_repairs_and_the_face_repairs_apart() -> None:
    steps: list[JsonValue] = [
        {"stage": "checking", "kind": "repair", "text": "a", "at": "t", "face": 2},
        {"stage": "checking", "kind": "repair", "text": "b", "at": "t"},
        {"stage": "checking", "kind": "repair", "text": "c", "at": "t", "face": 1},
        {"stage": "checking", "kind": "step", "text": "d", "at": "t", "face": 4},
    ]
    counts = counts_of(steps)
    assert (counts["repairs"], counts["face_repairs"]) == (3, 2)
    assert repairs_line(counts) == "Repairs: 3 (face: 2)"


# --- what a worker reads -------------------------------------------------------------------------


def test_write_roadmap_and_llms_txt_show_the_same_good_and_bad_step(settings: Settings) -> None:
    description = tool_catalog()["write_roadmap"].description
    shown = f'Step, good: "{FACE_STEP_GOOD}" Step, bad: "{FACE_STEP_BAD}"'
    assert shown in description and shown in FACE_RULE
    bootstrap = render_bootstrap(settings)
    section = bootstrap.split("### write_roadmap (", 1)[1].split("\n### ", 1)[0]
    assert section.splitlines()[2] == description
