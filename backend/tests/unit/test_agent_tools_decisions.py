"""``ask_person`` on the fakes: the real Loop, Ticket, outcome and request-state services on an
in-memory board, handed to the tool as the attributes ``DecisionAsking`` declares, with a clock the
test moves. The question in mode ``url`` when the client declared it, the address as text when it
did not or the installation has no public address, never the mode ``form`` without the setting and
the right (``test_agent_tools_editor_decisions.py`` has the form); ``not_pending``; the
repeated call before and after the decision for every decision; ``decline`` and ``cancel``; every
state that is refused; two keys of one person; and the scopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeIs

import pytest
from pydantic import JsonValue

from app.core.config import Settings
from app.core.context import ActorContext
from app.core.errors import Forbidden, ValidationFailure
from app.db.generated.board import LoopDocumentsRow, LoopsRow
from app.services.agent_tools import (
    NO_INPUT,
    InputRequired,
    ToolInput,
    ToolResult,
    ask_person,
    ask_person_with_input,
    tool_catalog,
)
from app.services.agent_tools_decisions import CALL_AGAIN, STILL_OPEN, ask_message
from app.services.auth import AuthService
from app.services.cards import CardService
from app.services.decision_links import decision_link
from app.services.decision_outcomes import AskedDecision, DecisionOutcomeService
from app.services.decision_requests import CLOSED, OPEN_FOR, REQUESTED, DecisionRequestService
from app.services.loop_documents import LoopDocumentService
from app.services.loop_history import LoopHistoryService
from app.services.loop_links import LoopWorkflowLinks
from app.services.loop_plans import LoopPlanService
from app.services.loop_qa import LoopQaService
from app.services.loops import LoopService
from app.services.request_state import (
    REQUEST_STATE_TTL,
    RefusalReason,
    RequestStateRefused,
    RequestStateService,
)
from app.services.ticket_work import TicketWorkService
from tests.unit.fakes.board import (
    BOARD_ID,
    BoardState,
    FakeBoardChecks,
    FakeBoardUnitOfWork,
    activity_row,
    approval_row,
    card_row,
    document_row,
    list_row,
    loop_row,
    qa_cycle_row,
)
from tests.unit.fakes.data_files import FakeBootstrapPasswordFile
from tests.unit.fakes.plans import FakePlanViews, plan_views
from tests.unit.fakes.registry import (
    FakeRegistryUnitOfWork,
    RegistryState,
    actor_row,
    credential_row,
    sign_in_row,
)
from tests.unit.test_loop_history_service import Files, Ids, Index

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
EARLIER = "2026-11-26T11:00:00Z"
DECIDED = "2026-11-26T12:05:00Z"
PUBLIC = "https://tralala.example.com"
SECRET = "ask-person-unit-secret-" + "s" * 24

LOOP = "11111111-1111-4111-8111-111111111111"
CARD = "22222222-2222-4222-8222-222222222222"
CYCLE = "33333333-3333-4333-8333-333333333333"
INFO, AI, HUMAN = "info-1", "analysis-ai-1", "analysis-1"
ROADMAP_AI, ROADMAP = "roadmap-ai-1", "roadmap-1"
TICKET_KEY = "L-1-UNP-001"

PERSON = "44444444-4444-4444-8444-444444444444"
PERSON_NAME = "Ada"
SCOPES = frozenset({"loops:read", "cards:read"})
# One person's two keys, and another person's key.
KEY = ActorContext(
    actor_id="key-actor-1",
    actor_type="agent",
    actor_name="Claude",
    scopes=SCOPES,
    credential_id="cred-1",
)
SECOND_KEY = KEY.__replace__(actor_name="Codex", credential_id="cred-2")
OTHER_KEY = KEY.__replace__(actor_id="key-actor-2", credential_id="cred-3")

OTHER_PERSON = "55555555-5555-4555-8555-555555555555"
# Each key: its credential, the actor it acts as, the person who issued it and its name.
KEYS = (
    ("cred-1", KEY.actor_id, PERSON, "Laptop"),
    ("cred-2", KEY.actor_id, PERSON, "Desktop"),
    ("cred-3", OTHER_KEY.actor_id, OTHER_PERSON, "Bo's laptop"),
)

URL = ToolInput(url=True)
FORM = ToolInput(form=True)
BOTH = ToolInput(form=True, url=True)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


@dataclass(frozen=True, slots=True)
class World:
    """What ``ask_person`` declares it uses of the composition root, and the board."""

    loop: LoopService
    card: CardService
    decision_outcome: DecisionOutcomeService
    decision_request: DecisionRequestService
    request_state: RequestStateService
    settings: Settings
    auth: AuthService
    loop_document: LoopDocumentService
    ticket_work: TicketWorkService
    loop_qa: LoopQaService
    state: BoardState
    registry: RegistryState
    clock: Clock


def _world(settings: Settings, loop: LoopsRow, public_url: str | None) -> World:
    board = BoardState()
    board.loops = {loop.id: loop}
    board.lists["todo"] = list_row("todo", loop.id, 512, name="Todo")
    registry = RegistryState()
    registry.actors[PERSON] = actor_row(PERSON, name=PERSON_NAME)
    registry.actors[OTHER_PERSON] = actor_row(OTHER_PERSON, name="Bo")
    registry.sign_ins[PERSON] = sign_in_row(PERSON)
    registry.sign_ins[OTHER_PERSON] = sign_in_row(OTHER_PERSON)
    for actor_id in (KEY.actor_id, OTHER_KEY.actor_id):
        registry.actors[actor_id] = actor_row(actor_id, type_="agent", name="session")
    for credential_id, actor_id, owner, name in KEYS:
        registry.credentials[credential_id] = credential_row(
            credential_id, actor_id, owner_actor_id=owner
        ).__replace__(name=name)
    views = plan_views(FakePlanViews())
    checks = FakeBoardChecks()
    store = FakeBoardUnitOfWork(board)
    accounts = FakeRegistryUnitOfWork(registry)
    clock = Clock(NOW)
    used = settings.model_copy(update={"public_url": public_url})
    ids = Ids()
    cards = CardService(used, checks, store, accounts, plans=views, clock=clock)
    history = LoopHistoryService(
        checks, store, Files(Path("unused")), Index(), clock=lambda: DECIDED, new_id=ids
    )
    return World(
        loop=LoopService(
            used, checks, store, plans=views, tickets=cards, clock=clock, new_id=ids
        ),
        card=cards,
        decision_outcome=DecisionOutcomeService(store, accounts),
        decision_request=DecisionRequestService(checks, store, accounts, clock=clock),
        request_state=RequestStateService(SECRET, clock=clock),
        settings=used,
        auth=AuthService(
            used, accounts, bootstrap_password_file=FakeBootstrapPasswordFile(), clock=clock
        ),
        loop_document=LoopDocumentService(
            checks, store, LoopPlanService(clock=lambda: NOW, new_id=ids), clock=clock, new_id=ids
        ),
        ticket_work=TicketWorkService(checks, store, cards, clock=clock, new_id=ids),
        loop_qa=LoopQaService(
            checks,
            store,
            history,
            LoopWorkflowLinks(),
            idempotency_ttl_seconds=3600,
            clock=clock,
            new_id=ids,
        ),
        state=board,
        registry=registry,
        clock=clock,
    )


def _loop(stage: str) -> LoopsRow:
    completed = "2026-11-25T09:00:00Z" if stage == "completed" else None
    row = loop_row(LOOP, stage=stage, completed_at=completed)
    return row.__replace__(active_qa_cycle_id=CYCLE if stage == "awaiting_qa" else None)


def _analysis_documents() -> list[LoopDocumentsRow]:
    return [
        document_row(INFO, LOOP, "info", status="ready_for_review"),
        document_row(AI, LOOP, "analysis_ai", status="ready_for_review", info=INFO),
        document_row(HUMAN, LOOP, "analysis", status="ready_for_review", info=INFO, analysis_ai=AI),
    ]


def world_for(
    settings: Settings, decision: AskedDecision, *, public_url: str | None = PUBLIC
) -> World:
    """A board on which ``decision`` waits for a person."""
    match decision:
        case "analysis":
            w = _world(settings, _loop("analysis_review"), public_url)
            w.state.documents = _analysis_documents()
        case "roadmap":
            w = _world(settings, _loop("roadmap_review"), public_url)
            w.state.documents = [
                document_row(INFO, LOOP, "info", status="approved", approved=True),
                document_row(AI, LOOP, "analysis_ai", status="approved", approved=True, info=INFO),
                document_row(
                    HUMAN,
                    LOOP,
                    "analysis",
                    status="approved",
                    approved=True,
                    info=INFO,
                    analysis_ai=AI,
                ),
                document_row(
                    ROADMAP_AI,
                    LOOP,
                    "roadmap_ai",
                    status="ready_for_review",
                    info=INFO,
                    analysis_ai=AI,
                    analysis=HUMAN,
                ),
                document_row(
                    ROADMAP,
                    LOOP,
                    "roadmap",
                    status="ready_for_review",
                    info=INFO,
                    analysis_ai=AI,
                    analysis=HUMAN,
                    roadmap_ai=ROADMAP_AI,
                ),
            ]
            revisions = {"info": INFO, "analysis_ai": AI, "analysis": HUMAN}
            w.state.approvals.append(
                approval_row(
                    "approved-analysis",
                    LOOP,
                    "analysis",
                    revisions_json=json.dumps(revisions),
                    created_at=EARLIER,
                )
            )
            w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(
                analysis_approval_id="approved-analysis"
            )
        case "implementation":
            w = _world(settings, _loop("in_progress"), public_url)
        case "qa":
            w = _world(settings, _loop("awaiting_qa"), public_url)
            w.state.qa_cycles[CYCLE] = qa_cycle_row(CYCLE, LOOP, 1, status="in_progress")
        case "wait":
            w = _world(settings, _loop("in_progress"), public_url)
            w.state.cards[CARD] = card_row(CARD, "todo", LOOP).__replace__(
                ticket_key=TICKET_KEY,
                waiting_for="decision",
                waiting_reason="Which mail service do we use?",
                waiting_set_at=EARLIER,
                waiting_set_by=KEY.actor_id,
            )
        case "confirmation":
            w = _world(settings, _loop("in_progress"), public_url)
            w.state.cards[CARD] = card_row(CARD, "todo", LOOP).__replace__(
                ticket_key=TICKET_KEY, required_actor="human"
            )
    return w


def args_for(decision: AskedDecision, **changes: JsonValue) -> dict[str, JsonValue]:
    arguments: dict[str, JsonValue] = {"board_id": BOARD_ID, "loop_id": LOOP, "decision": decision}
    if decision in ("wait", "confirmation"):
        arguments["card_id"] = CARD
    arguments.update(changes)
    return arguments


def call(
    w: World,
    decision: AskedDecision,
    given: ToolInput = URL,
    actor: ActorContext = KEY,
    **changes: JsonValue,
) -> ToolResult | InputRequired:
    return ask_person_with_input(w, actor, args_for(decision, **changes), given)


def asked(answer: ToolResult | InputRequired) -> InputRequired:
    assert isinstance(answer, InputRequired), answer
    return answer


def complete(answer: ToolResult | InputRequired) -> ToolResult:
    assert isinstance(answer, dict), answer
    return answer


def retry(state: str, action: str | None = "accept") -> ToolInput:
    responses: dict[str, Mapping[str, JsonValue]] = {}
    if action is not None:
        responses["decision"] = {"action": action}
    return ToolInput(url=True, responses=responses, request_state=state)


def _is_fields(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def params(question: InputRequired) -> Mapping[str, object]:
    request = question.input_requests["decision"]
    assert request["method"] == "elicitation/create"
    found = request["params"]
    assert _is_fields(found)
    return found


def card_id_of(decision: AskedDecision) -> str | None:
    return CARD if decision in ("wait", "confirmation") else None


def link_of(decision: AskedDecision, public_url: str | None = PUBLIC) -> str:
    return decision_link(
        decision,
        board_id=BOARD_ID,
        loop_id=LOOP,
        card_id=card_id_of(decision),
        public_url=public_url,
    )


# --- what a person decides, as the services that take it write it ------------------------------


def _review(w: World, scope: str, decision: str, kinds: tuple[str, ...]) -> None:
    current = {row.kind: row.id for row in w.state.documents if row.is_current}
    revisions = {kind: current[kind] for kind in kinds}
    w.state.approvals.append(
        approval_row(
            f"{scope}-{decision}",
            LOOP,
            scope,
            decision=decision,
            revisions_json=json.dumps(revisions),
            created_at=DECIDED,
        ).__replace__(reviewer_actor_id=PERSON, reviewer_name=PERSON_NAME)
    )


def decide(w: World, decision: AskedDecision, outcome: str) -> None:
    """``outcome`` taken on ``decision`` at ``DECIDED`` by the person."""
    match decision:
        case "analysis":
            _review(w, "analysis", outcome, ("info", "analysis_ai", "analysis"))
        case "roadmap":
            kinds = ("info", "analysis_ai", "analysis", "roadmap_ai", "roadmap")
            _review(w, "roadmap", outcome, kinds)
        case "implementation":
            w.state.approvals.append(
                approval_row(
                    "implementation", LOOP, "implementation", created_at=DECIDED
                ).__replace__(reviewer_actor_id=PERSON, reviewer_name=PERSON_NAME)
            )
        case "qa":
            w.state.qa_cycles[CYCLE] = w.state.qa_cycles[CYCLE].__replace__(
                status=outcome, decided_at=DECIDED, decided_by_actor_id=PERSON
            )
        case "wait":
            w.state.cards[CARD] = w.state.cards[CARD].__replace__(
                waiting_for="nothing", waiting_reason="", waiting_set_at=None, waiting_set_by=None
            )
            w.state.activity.append(
                activity_row(
                    "cleared",
                    "card.wait_cleared",
                    CARD,
                    actor_id=PERSON,
                    actor_type="user",
                    timestamp=DECIDED,
                )
            )
        case "confirmation":
            w.state.cards[CARD] = w.state.cards[CARD].__replace__(
                human_confirmed_at=DECIDED, human_confirmed_by_actor_id=PERSON
            )


DECISIONS: tuple[AskedDecision, ...] = (
    "analysis",
    "roadmap",
    "wait",
    "confirmation",
    "implementation",
    "qa",
)
OUTCOMES: list[tuple[AskedDecision, str]] = [
    ("analysis", "approved"),
    ("analysis", "changes_requested"),
    ("roadmap", "approved"),
    ("roadmap", "changes_requested"),
    ("wait", "cleared"),
    ("confirmation", "confirmed"),
    ("implementation", "accepted"),
    ("qa", "accepted"),
    ("qa", "rejected"),
]


# --- asking ------------------------------------------------------------------------------------


@pytest.mark.parametrize("decision", DECISIONS)
def test_a_client_with_the_url_mode_is_asked_with_the_decisions_address(
    settings: Settings, decision: AskedDecision
) -> None:
    w = world_for(settings, decision)
    question = asked(call(w, decision))
    assert set(question.input_requests) == {"decision"}
    found = params(question)
    assert found["mode"] == "url"
    assert found["url"] == link_of(decision)
    assert str(found["url"]).startswith(PUBLIC + "/boards/")
    assert found["message"] == ask_message(decision, "L-1", card_id_of(decision) and TICKET_KEY)
    assert "requestedSchema" not in found
    # The state opens for this key and this call, and carries no id the client could read.
    assert LOOP not in question.request_state
    assert KEY.actor_id not in question.request_state


def test_the_address_carries_only_ids(settings: Settings) -> None:
    w = world_for(settings, "wait")
    question = asked(call(w, "wait"))
    address = str(params(question)["url"])
    assert address == f"{PUBLIC}/boards/{BOARD_ID}/loops/{LOOP}/tickets/{CARD}?focus=clear-wait"
    assert question.request_state not in address
    assert "cred-1" not in address and "token" not in address


@pytest.mark.parametrize(
    ("decision", "message"),
    [
        ("analysis", "Open Tralala to approve the analysis of L-1 or ask for changes."),
        ("roadmap", "Open Tralala to approve the RoadMap of L-1 or ask for changes."),
        ("wait", "Open Tralala to answer and clear the wait on L-1-UNP-001 in L-1."),
        (
            "confirmation",
            "Open Tralala to confirm that the person's task L-1-UNP-001 in L-1 is done.",
        ),
        ("implementation", "Open Tralala to accept the implementation of L-1."),
        ("qa", "Open Tralala to accept or reject the QA of L-1."),
    ],
)
def test_the_message_names_the_loop_the_decision_and_the_ticket(
    settings: Settings, decision: AskedDecision, message: str
) -> None:
    w = world_for(settings, decision)
    assert params(asked(call(w, decision)))["message"] == message


@pytest.mark.parametrize("given", [NO_INPUT, FORM])
@pytest.mark.parametrize("decision", DECISIONS)
def test_a_client_without_the_url_mode_gets_the_address_as_text(
    settings: Settings, decision: AskedDecision, given: ToolInput
) -> None:
    w = world_for(settings, decision)
    answer = complete(call(w, decision, given))
    assert answer["status"] == "waiting_for_person"
    assert answer["decision"] == decision
    assert answer["decision_link"] == link_of(decision)
    assert answer["next_step"] == CALL_AGAIN
    assert "again later" in CALL_AGAIN


@pytest.mark.parametrize("given", [URL, BOTH])
def test_without_a_public_address_even_a_url_client_gets_the_path_as_text(
    settings: Settings, given: ToolInput
) -> None:
    w = world_for(settings, "analysis", public_url=None)
    answer = complete(call(w, "analysis", given))
    assert answer["status"] == "waiting_for_person"
    assert answer["decision_link"] == f"/boards/{BOARD_ID}/loops/{LOOP}?tab=plan&doc=analysis"


def test_without_the_setting_and_the_right_the_form_mode_is_never_used(
    settings: Settings,
) -> None:
    w = world_for(settings, "analysis")
    assert w.settings.editor_decisions is False
    assert params(asked(call(w, "analysis", BOTH)))["mode"] == "url"
    assert complete(call(w, "analysis", FORM))["status"] == "waiting_for_person"


def test_the_catalogue_handler_asks_nothing_and_gives_the_address(settings: Settings) -> None:
    w = world_for(settings, "qa")
    answer = ask_person(w, KEY, args_for("qa"))
    assert answer["status"] == "waiting_for_person"
    assert answer["decision_link"] == link_of("qa")


# --- not pending -------------------------------------------------------------------------------


def test_an_analysis_that_is_not_under_review_is_not_pending(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(stage="draft")
    answer = complete(call(w, "analysis"))
    assert answer["status"] == "not_pending"
    assert str(answer["why"]).startswith("The analysis of L-1 does not wait for a person now.")


def test_the_roadmap_is_not_pending_while_the_analysis_is_under_review(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    assert complete(call(w, "roadmap"))["status"] == "not_pending"


def test_a_ticket_that_waits_for_nothing_has_no_wait_to_ask_about(settings: Settings) -> None:
    w = world_for(settings, "confirmation")
    answer = complete(call(w, "wait"))
    assert answer == {
        "status": "not_pending",
        "decision": "wait",
        "loop_key": "L-1",
        "ticket_key": TICKET_KEY,
        "why": "Ticket L-1-UNP-001 waits for nothing.",
    }


def test_a_ticket_that_is_no_persons_task_has_nothing_to_confirm(settings: Settings) -> None:
    w = world_for(settings, "wait")
    assert complete(call(w, "confirmation"))["why"] == "Ticket L-1-UNP-001 is not a person's task."


def test_a_confirmed_or_completed_ticket_is_not_pending(settings: Settings) -> None:
    w = world_for(settings, "confirmation")
    decide(w, "confirmation", "confirmed")
    assert complete(call(w, "confirmation"))["why"] == "Ticket L-1-UNP-001 is already confirmed."
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(completed_at=DECIDED)
    assert complete(call(w, "confirmation"))["why"] == (
        "Ticket L-1-UNP-001 is completed: nothing on it waits for a person."
    )


def test_nothing_in_a_read_only_loop_waits_for_a_person(settings: Settings) -> None:
    w = world_for(settings, "wait")
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(stage="completed", completed_at=EARLIER)
    answer = complete(call(w, "wait"))
    assert answer["status"] == "not_pending"
    assert (
        answer["why"]
        == "The Loop L-1 is completed and read-only: nothing in it waits for a person."
    )


# --- the repeated call -------------------------------------------------------------------------


@pytest.mark.parametrize("decision", DECISIONS)
def test_before_the_decision_the_retry_asks_again_with_a_new_state(
    settings: Settings, decision: AskedDecision
) -> None:
    w = world_for(settings, decision)
    first = asked(call(w, decision)).request_state
    second = asked(call(w, decision, retry(first)))
    assert second.request_state != first
    assert params(second)["url"] == link_of(decision)
    # The first state is used up; the new one opens.
    with pytest.raises(RequestStateRefused) as refused:
        call(w, decision, retry(first))
    assert refused.value.reason == "reused"
    assert isinstance(call(w, decision, retry(second.request_state)), InputRequired)


@pytest.mark.parametrize(("decision", "outcome"), OUTCOMES)
def test_after_the_decision_the_retry_says_what_was_decided_by_whom_and_when(
    settings: Settings, decision: AskedDecision, outcome: str
) -> None:
    w = world_for(settings, decision)
    state = asked(call(w, decision)).request_state
    decide(w, decision, outcome)
    answer = complete(call(w, decision, retry(state)))
    assert answer == {
        "status": "decided",
        "decision": decision,
        "loop_key": "L-1",
        "ticket_key": TICKET_KEY if card_id_of(decision) else None,
        "outcome": outcome,
        "decided_by": PERSON_NAME,
        "decided_by_id": PERSON,
        "decided_at": DECIDED,
    }


def test_a_retry_without_an_answer_but_with_the_state_asks_again(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    assert isinstance(call(w, "analysis", retry(state, action=None)), InputRequired)


def test_a_retry_without_an_answer_still_reports_a_decision_taken(settings: Settings) -> None:
    w = world_for(settings, "wait")
    state = asked(call(w, "wait")).request_state
    decide(w, "wait", "cleared")
    assert complete(call(w, "wait", retry(state, action=None)))["outcome"] == "cleared"


@pytest.mark.parametrize(("action", "status"), [("decline", "declined"), ("cancel", "cancelled")])
def test_a_declined_or_cancelled_question_leaves_the_decision_open(
    settings: Settings, action: str, status: str
) -> None:
    w = world_for(settings, "implementation")
    state = asked(call(w, "implementation")).request_state
    answer = complete(call(w, "implementation", retry(state, action)))
    assert answer == {
        "status": status,
        "decision": "implementation",
        "loop_key": "L-1",
        "ticket_key": None,
        "decision_link": link_of("implementation"),
        "next_step": STILL_OPEN,
    }
    # Still open: a new question asks again.
    assert isinstance(call(w, "implementation"), InputRequired)


def test_an_older_decision_on_the_same_thing_is_not_the_answer(settings: Settings) -> None:
    """Only what was decided after the question counts: a QA decision dated before it was asked
    is no answer to it."""
    w = world_for(settings, "qa")
    state = asked(call(w, "qa")).request_state
    w.state.qa_cycles[CYCLE] = w.state.qa_cycles[CYCLE].__replace__(
        decided_at=EARLIER, decided_by_actor_id=PERSON
    )
    assert isinstance(call(w, "qa", retry(state)), InputRequired)


def test_a_question_that_waits_for_nothing_any_more_is_not_pending(settings: Settings) -> None:
    w = world_for(settings, "qa")
    state = asked(call(w, "qa")).request_state
    w.state.loops[LOOP] = w.state.loops[LOOP].__replace__(stage="cancelled", cancelled_at=DECIDED)
    assert complete(call(w, "qa", retry(state)))["status"] == "not_pending"


# --- refused states ----------------------------------------------------------------------------


def _refused(w: World, decision: AskedDecision, given: ToolInput, actor: ActorContext = KEY) -> str:
    with pytest.raises(RequestStateRefused) as refused:
        call(w, decision, given, actor)
    reason: RefusalReason = refused.value.reason
    return reason


def test_a_changed_state_is_refused(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    middle = len(state) // 2
    changed = state[:middle] + ("A" if state[middle] != "A" else "B") + state[middle + 1 :]
    assert _refused(w, "analysis", retry(changed)) == "invalid"


def test_an_expired_state_is_refused(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    w.clock.moment = NOW + REQUEST_STATE_TTL
    assert _refused(w, "analysis", retry(state)) == "expired"


def test_another_persons_key_is_refused(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    assert _refused(w, "analysis", retry(state), OTHER_KEY) == "wrong_actor"


def test_another_key_of_the_same_person_is_refused(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    assert _refused(w, "analysis", retry(state), SECOND_KEY) == "wrong_credential"


def test_a_state_for_another_call_is_refused(settings: Settings) -> None:
    w = world_for(settings, "wait")
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(required_actor="human")
    state = asked(call(w, "wait")).request_state
    assert _refused(w, "confirmation", retry(state)) == "wrong_call"


def test_a_used_state_is_refused(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    call(w, "analysis", retry(state, "decline"))
    assert _refused(w, "analysis", retry(state)) == "reused"


def test_a_state_whose_question_is_out_of_date_is_refused(settings: Settings) -> None:
    """Another analysis was handed in while the person had not decided: the question was about a
    revision that no longer waits, so the key asks again without the state."""
    w = world_for(settings, "analysis")
    state = asked(call(w, "analysis")).request_state
    w.state.documents = [
        row.__replace__(is_current=0) if row.kind == "analysis" else row
        for row in w.state.documents
    ] + [
        document_row(
            "analysis-2",
            LOOP,
            "analysis",
            revision=2,
            status="ready_for_review",
            info=INFO,
            analysis_ai=AI,
        )
    ]
    assert _refused(w, "analysis", retry(state)) == "wrong_call"
    assert isinstance(call(w, "analysis"), InputRequired)


# --- several keys of one person ----------------------------------------------------------------


def test_two_keys_of_one_person_each_get_their_own_state_and_the_same_answer(
    settings: Settings,
) -> None:
    w = world_for(settings, "roadmap")
    first = asked(call(w, "roadmap", actor=KEY)).request_state
    second = asked(call(w, "roadmap", actor=SECOND_KEY)).request_state
    assert first != second
    assert _refused(w, "roadmap", retry(first), SECOND_KEY) == "wrong_credential"
    decide(w, "roadmap", "approved")
    answers = [
        complete(call(w, "roadmap", retry(first), KEY)),
        complete(call(w, "roadmap", retry(second), SECOND_KEY)),
    ]
    assert [answer["decided_by_id"] for answer in answers] == [PERSON, PERSON]
    assert [answer["outcome"] for answer in answers] == ["approved", "approved"]


# --- arguments and scopes ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "argument"),
    [
        ({"decision": "info"}, "decision"),
        ({"decision": None}, "decision"),
        ({"decision": "wait", "card_id": None}, "card_id"),
        ({"card_id": CARD}, "card_id"),
        ({"loop_id": None}, "loop_id"),
    ],
)
def test_the_arguments_are_checked(
    settings: Settings, changes: dict[str, JsonValue], argument: str
) -> None:
    w = world_for(settings, "analysis")
    arguments = {**args_for("analysis"), **changes}
    with pytest.raises(ValidationFailure) as refused:
        ask_person_with_input(w, KEY, arguments, URL)
    assert refused.value.details is not None
    assert refused.value.details["argument"] == argument


@pytest.mark.parametrize("missing", ["loops:read", "cards:read"])
def test_the_tool_needs_both_read_scopes(settings: Settings, missing: str) -> None:
    w = world_for(settings, "analysis")
    actor = KEY.__replace__(scopes=SCOPES - {missing})
    with pytest.raises(Forbidden):
        call(w, "analysis", actor=actor)


def test_the_catalogue_entry_reads_and_asks() -> None:
    tool = tool_catalog()["ask_person"]
    assert tool.scopes == ("loops:read", "cards:read")
    assert tool.handler is ask_person
    assert tool.asks is ask_person_with_input
    assert tool.input_schema["required"] == ["board_id", "loop_id", "decision"]
    assert set(tool.input_schema["properties"]) == {"board_id", "loop_id", "decision", "card_id"}
    assert "you never fill it in" in tool.description
    others = [entry.name for entry in tool_catalog().values() if entry.asks is not None]
    assert others == ["ask_person"]


def test_a_wait_a_person_replaced_counts_as_cleared_but_a_keys_does_not(settings: Settings) -> None:
    w = world_for(settings, "wait")
    state = asked(call(w, "wait")).request_state
    w.state.activity.append(
        activity_row("set-by-key", "card.wait_set", CARD, actor_id=KEY.actor_id, timestamp=DECIDED)
    )
    state = asked(call(w, "wait", retry(state))).request_state
    w.state.activity.append(
        activity_row(
            "set-by-person",
            "card.wait_set",
            CARD,
            actor_id=PERSON,
            actor_type="user",
            timestamp=DECIDED,
        )
    )
    answer = complete(call(w, "wait", retry(state)))
    assert (answer["outcome"], answer["decided_by"]) == ("cleared", PERSON_NAME)


# --- the question in the board's history -------------------------------------------------------


def requests(w: World, action: str = REQUESTED) -> list[dict[str, object]]:
    rows = [row for row in w.state.activity if row.action == action]
    found: list[dict[str, object]] = []
    for row in rows:
        changes: JsonValue = json.loads(row.changes_json)
        assert isinstance(changes, dict)
        found.append({"entity": (row.entity_type, row.entity_id), "by": row.actor_id, **changes})
    return found


@pytest.mark.parametrize("decision", DECISIONS)
def test_the_first_question_writes_one_row_on_its_target(
    settings: Settings, decision: AskedDecision
) -> None:
    w = world_for(settings, decision)
    state = asked(call(w, decision)).request_state
    target = ("card", CARD) if card_id_of(decision) else ("loop", LOOP)
    assert requests(w) == [
        {
            "entity": target,
            "by": KEY.actor_id,
            "decision": decision,
            "credential_id": "cred-1",
            "key_name": "Laptop",
            "owner_name": PERSON_NAME,
            "via": "link",
        }
    ]
    # Asking again while the question is open, with the state or without, writes no row.
    asked(call(w, decision, retry(state)))
    complete(call(w, decision, NO_INPUT))
    assert len(requests(w)) == 1


def test_each_key_writes_its_own_row_and_the_owner_is_the_person_who_issued_it(
    settings: Settings,
) -> None:
    w = world_for(settings, "wait")
    for actor in (KEY, SECOND_KEY, OTHER_KEY, KEY):
        call(w, "wait", actor=actor)
    assert [(row["key_name"], row["owner_name"]) for row in requests(w)] == [
        ("Laptop", PERSON_NAME),
        ("Desktop", PERSON_NAME),
        ("Bo's laptop", "Bo"),
    ]


def test_a_question_that_lapsed_is_asked_again_with_a_new_row(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    call(w, "analysis")
    w.clock.moment = NOW + OPEN_FOR - timedelta(seconds=1)
    call(w, "analysis")
    assert len(requests(w)) == 1
    w.clock.moment = NOW + OPEN_FOR
    call(w, "analysis")
    assert len(requests(w)) == 2


def test_a_declined_question_is_closed_and_the_next_one_is_new(settings: Settings) -> None:
    w = world_for(settings, "qa")
    state = asked(call(w, "qa")).request_state
    complete(call(w, "qa", retry(state, "decline")))
    assert [row["reason"] for row in requests(w, CLOSED)] == ["declined"]
    assert requests(w, CLOSED)[0]["credential_id"] == "cred-1"
    call(w, "qa")
    assert len(requests(w)) == 2


def test_nothing_is_written_when_nothing_waits(settings: Settings) -> None:
    w = world_for(settings, "analysis")
    complete(call(w, "roadmap"))
    assert requests(w) == []


def test_a_question_answered_by_a_decision_is_no_longer_open(settings: Settings) -> None:
    w = world_for(settings, "wait")
    call(w, "wait")
    decide(w, "wait", "cleared")
    w.state.cards[CARD] = w.state.cards[CARD].__replace__(
        waiting_for="decision", waiting_set_at=DECIDED
    )
    w.clock.moment = NOW + timedelta(minutes=10)
    call(w, "wait")
    assert len(requests(w)) == 2

