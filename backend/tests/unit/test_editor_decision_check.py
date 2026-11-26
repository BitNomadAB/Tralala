"""The explicit check for deciding in the editor, on each decision service (AGENTS.md rule 11a).

``ActorContext.require_human`` refuses every context that came through a key. Only the four methods
of the five decisions a person may take in the editor call ``require_person_or_editor_decision``,
which also lets through the owner's context ``AuthService.editor_decision_actor`` builds for a key
with the right: approving the analysis or the RoadMap, clearing a wait, confirming a person's task
and accepting the implementation of a Loop with a plan. A reset, QA's decision, finalizing or
cancelling a Loop, replacing a wait and issuing or rotating a key refuse that context; so does the
implementation of a Loop without a plan, or one that passes QA or leaves Tickets unfinished. Each
service runs its real code on the fakes of its own unit tests."""

# The worlds of the services' own tests are reused, private helpers included.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.context import ActorContext, EditorDecision
from app.core.errors import Forbidden
from app.schemas.auth import CredentialCreate
from app.schemas.cards import TicketWaitClear
from app.schemas.loops import (
    ApprovalRequest,
    HumanConfirmation,
    ImplementationAcceptance,
    LoopCancel,
    QaDecision,
    ScopeResetRequest,
)
from tests.unit import test_auth_service as accounts
from tests.unit import test_loop_document_service as documents
from tests.unit import test_loop_history_service as histories
from tests.unit import test_loop_qa_service as qa
from tests.unit import test_loop_service as loops
from tests.unit import test_ticket_work as work
from tests.unit.fakes.board import BOARD_ID

LAPTOP = EditorDecision(credential_id="key-1", key_name="Laptop")
TAKEN = {"credential_id": "key-1", "key_name": "Laptop", "via": "form"}


def through_key(person: ActorContext) -> ActorContext:
    """``person``'s context as ``AuthService.editor_decision_actor`` builds it for the key."""
    return person.__replace__(credential_id=LAPTOP.credential_id, editor_decision=LAPTOP)


def refused(error: pytest.ExceptionInfo[Forbidden]) -> None:
    assert error.value.code == "human_action_required"


# --- the context itself ---------------------------------------------------------------------


def test_the_explicit_check_lets_a_person_and_the_owners_context_through() -> None:
    person = documents.HUMAN
    person.require_person_or_editor_decision("Approving an analysis")
    through_key(person).require_person_or_editor_decision("Approving an analysis")


@pytest.mark.parametrize(
    "context",
    [
        documents.AGENT,
        documents.AGENT.__replace__(credential_id="key-1", editor_decision=LAPTOP),
        documents.HUMAN.__replace__(credential_id="key-1"),
        documents.HUMAN.__replace__(credential_id="key-2", editor_decision=LAPTOP),
    ],
    ids=["key", "key-claiming-a-grant", "person-through-a-key", "grant-of-another-key"],
)
def test_the_explicit_check_refuses_everything_else(context: ActorContext) -> None:
    with pytest.raises(Forbidden) as error:
        context.require_person_or_editor_decision("Approving an analysis")
    refused(error)


def test_require_human_refuses_the_owners_context_of_a_key() -> None:
    documents.HUMAN.require_human("Resetting the analysis")
    with pytest.raises(Forbidden) as error:
        through_key(documents.HUMAN).require_human("Resetting the analysis")
    refused(error)
    assert error.value.details == {"action": "Resetting the analysis", "actor_type": "user"}


# --- reviews and resets ---------------------------------------------------------------------


def test_the_owner_approves_the_analysis_through_the_key_and_history_says_so() -> None:
    w = documents.world()
    documents.info(w)
    documents.analysis(w)
    request = ApprovalRequest(decision="approved", version=w.loop.version)
    w.service.review(through_key(documents.HUMAN), BOARD_ID, documents.LOOP, "analysis", request)
    (approval,) = w.state.approvals
    assert (approval.reviewer_actor_id, approval.decision) == ("actor-1", "approved")
    (row,) = [row for row in w.state.activity if row.action == "loop.analysis_reviewed"]
    assert json.loads(row.changes_json or "{}")["taken_through"] == TAKEN


def test_a_persons_own_review_carries_no_mark_of_a_key() -> None:
    w = documents.world()
    documents.approved_analysis(w)
    (row,) = [row for row in w.state.activity if row.action == "loop.analysis_reviewed"]
    assert "taken_through" not in json.loads(row.changes_json or "{}")


@pytest.mark.parametrize("scope", ["analysis", "roadmap"])
def test_a_reset_refuses_the_owners_context_of_a_key(scope: str) -> None:
    w = documents.world()
    documents.approved_analysis(w)
    with pytest.raises(Forbidden) as error:
        w.service.reset(
            through_key(documents.HUMAN),
            BOARD_ID,
            documents.LOOP,
            scope,
            ScopeResetRequest(version=w.loop.version),
        )
    refused(error)


# --- waits and confirmations ----------------------------------------------------------------


def test_the_owner_clears_a_wait_through_the_key_but_never_replaces_one(settings: Settings) -> None:
    w = work.world(settings)
    w.ticket_work.set_wait(work.WORKER, BOARD_ID, work.LOOP, "t", work.wait("third_party", "X"))
    owner = through_key(work.PERSON)
    with pytest.raises(Forbidden) as error:
        w.ticket_work.set_wait(owner, BOARD_ID, work.LOOP, "t", work.wait(version=2))
    refused(error)
    cleared = w.ticket_work.clear_wait(owner, BOARD_ID, work.LOOP, "t", TicketWaitClear(version=2))
    assert cleared["waiting_for"] == "nothing"
    (row,) = [row for row in w.state.activity if row.action == "card.wait_cleared"]
    assert (row.actor_id, row.actor_type) == ("person-1", "user")
    assert json.loads(row.changes_json or "{}")["taken_through"] == TAKEN
    (comment,) = w.state.comments.values()
    assert comment.content == (
        "Grace cleared the wait on this Ticket in a coding session through the key Laptop."
    )


def test_the_owner_confirms_a_persons_task_through_the_key(settings: Settings) -> None:
    w = loops._human_ticket(settings)
    owner = through_key(loops.HUMAN)
    w.service.confirm_human_ticket(owner, BOARD_ID, loops.LOOP, "h", HumanConfirmation(version=1))
    assert w.state.cards["h"].human_confirmed_by_actor_id == loops.HUMAN.actor_id
    (comment,) = w.state.comments.values()
    assert "in a coding session through the key Laptop" in comment.content


def test_cancelling_a_loop_refuses_the_owners_context_of_a_key(settings: Settings) -> None:
    w = loops.world(settings, loops.loop_row(loops.LOOP))
    with pytest.raises(Forbidden) as error:
        w.service.cancel(through_key(loops.HUMAN), BOARD_ID, loops.LOOP, LoopCancel(version=1))
    refused(error)


# --- the implementation, QA and finalizing --------------------------------------------------


def test_the_owner_accepts_the_implementation_through_the_key_and_qa_begins(
    tmp_path: Path,
) -> None:
    service, state, _ = qa.make(tmp_path)
    owner = through_key(qa.ADA)
    service.accept_implementation(owner, BOARD_ID, qa.LOOP, ImplementationAcceptance(version=1))
    (approval,) = [row for row in state.approvals if row.scope == "implementation"]
    assert json.loads(approval.revisions_json)["taken_through"] == TAKEN
    assert state.loops[qa.LOOP].completed_at is None


@pytest.mark.parametrize(
    "fields",
    [
        {"qa_status": "passed", "attestation": {"scope": "all", "results": "ok"}},
        {"accept_unfinished": True},
    ],
    ids=["passing-qa", "leaving-tickets-unfinished"],
)
def test_an_acceptance_that_would_close_the_loop_refuses_the_owners_context(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    service, state, _ = qa.make(tmp_path, open_ticket="accept_unfinished" in fields)
    payload = ImplementationAcceptance.model_validate({"version": 1, **fields})
    with pytest.raises(Forbidden) as error:
        service.accept_implementation(through_key(qa.ADA), BOARD_ID, qa.LOOP, payload)
    refused(error)
    assert state.approvals == []


def test_closing_a_loop_without_a_plan_refuses_the_owners_context(tmp_path: Path) -> None:
    service, state, _, _ = qa.make_without_plan(tmp_path)
    with pytest.raises(Forbidden) as error:
        service.accept_implementation(
            through_key(qa.ADA), BOARD_ID, qa.LOOP, ImplementationAcceptance(version=1)
        )
    refused(error)
    assert state.loops[qa.LOOP].completed_at is None


def test_qas_decision_refuses_the_owners_context_of_a_key(tmp_path: Path) -> None:
    service, state, _ = qa.make(tmp_path)
    qa.accept(service)
    (cycle,) = state.qa_cycles.values()
    decision = QaDecision(version=2, cycle_id=cycle.id, decision="accepted")
    with pytest.raises(Forbidden) as error:
        service.decide(through_key(qa.ADA), BOARD_ID, qa.LOOP, decision)
    refused(error)
    assert state.loops[qa.LOOP].completed_at is None


def test_finalizing_refuses_the_owners_context_of_a_key(tmp_path: Path) -> None:
    service, _, store = histories.make(tmp_path)
    with store.writer(BOARD_ID) as repos, pytest.raises(Forbidden) as error:
        service.finalize(
            repos,
            histories.LOOP,
            actor=through_key(histories.ADA),
            qa_approval_id="approval-1",
            attestation={},
            board_id=BOARD_ID,
        )
    refused(error)


# --- keys ------------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["issue", "rotate"])
def test_issuing_or_rotating_a_key_refuses_the_owners_context(
    settings: Settings, action: str
) -> None:
    registry = accounts.make_registry(settings.model_copy(update={"editor_decisions": True}))
    accounts.add_token(registry, "t-1")
    owner = through_key(accounts.MEMBER)
    with pytest.raises(Forbidden) as error:
        if action == "issue":
            registry.service.create_credential(
                owner,
                CredentialCreate.model_validate({"name": "Again", "scopes": ["cards:read"]}),
            )
        else:
            registry.service.rotate_credential(owner, "t-1")
    refused(error)
    assert list(registry.state.credentials) == ["t-1"]
