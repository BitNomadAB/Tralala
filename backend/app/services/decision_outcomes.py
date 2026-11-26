"""What a person decided after a key asked them: the outcome, who decided and when.

``ask_person`` (``agent_tools_decisions``) asks a person for one decision and, when the key calls
again, says whether it was taken. This module reads what the board already records about each
decision; it writes nothing and takes no decision:

- an analysis or a RoadMap: the review (``loop_approvals``) of that scope bound to exactly the
  revisions the question was about, ``approved`` or ``changes_requested``;
- the implementation: an acceptance (``loop_approvals``, scope ``implementation``), ``accepted``;
- QA: the QA cycle the question was about, decided ``accepted`` or ``rejected``;
- a Ticket's wait: a person clearing it, or replacing it with another (``card.wait_cleared`` or a
  person's ``card.wait_set`` in the activity log), ``cleared``;
- a person's task: its confirmation on the Ticket, ``confirmed``.

Only what was decided at or after ``since`` (when the question was asked, ISO 8601 UTC with whole
seconds as every timestamp here is written) counts, so an older decision on the same thing is never
taken for the answer. Who decided is the person's actor id and their name in the registry; it is
the same person whichever of their keys asked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict

from pydantic import JsonValue

from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork

AskedDecision = Literal["analysis", "roadmap", "wait", "confirmation", "implementation", "qa"]
ASKED_DECISIONS: tuple[AskedDecision, ...] = (
    "analysis",
    "roadmap",
    "wait",
    "confirmation",
    "implementation",
    "qa",
)
# The decisions taken on a Ticket's page, which need its id.
TICKET_DECISIONS: tuple[AskedDecision, ...] = ("wait", "confirmation")

Outcome = Literal["approved", "changes_requested", "cleared", "confirmed", "accepted", "rejected"]
# The newest activity entries of one kind on one Ticket that are read for a wait's answer.
_ACTIVITY_PAGE = 50


class DecisionTaken(TypedDict):
    """A decision a person took: what they decided, who they are and when."""

    outcome: Outcome
    decided_by_id: str
    decided_by: str | None
    decided_at: str


@dataclass(frozen=True, slots=True)
class _Found:
    outcome: Outcome
    actor_id: str
    name: str | None
    at: str


def _revisions(subject: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    revisions = subject.get("revisions")
    return revisions if isinstance(revisions, dict) else None


def _review(
    repos: BoardRepositories,
    loop_id: str,
    scope: str,
    subject: Mapping[str, JsonValue],
    since: str,
) -> _Found | None:
    revisions = _revisions(subject)
    if revisions is None:
        return None
    for row in repos.approvals.newest_first(loop_id):
        if row.scope != scope or row.created_at < since:
            continue
        if row.decision not in ("approved", "changes_requested"):
            continue
        bound: JsonValue = json.loads(row.revisions_json)
        if bound == revisions:
            outcome: Outcome = "approved" if row.decision == "approved" else "changes_requested"
            return _Found(outcome, row.reviewer_actor_id, row.reviewer_name, row.created_at)
    return None


def _implementation(repos: BoardRepositories, loop_id: str, since: str) -> _Found | None:
    for row in repos.approvals.newest_first(loop_id):
        if row.scope == "implementation" and row.decision == "approved" and row.created_at >= since:
            return _Found("accepted", row.reviewer_actor_id, row.reviewer_name, row.created_at)
    return None


def _qa(
    repos: BoardRepositories, loop_id: str, subject: Mapping[str, JsonValue], since: str
) -> _Found | None:
    cycle_id = subject.get("cycle_id")
    for cycle in repos.qa.cycles(loop_id):
        if cycle.id != cycle_id or cycle.decided_at is None or cycle.decided_at < since:
            continue
        if cycle.decided_by_actor_id is None:
            continue
        if cycle.status == "accepted":
            return _Found("accepted", cycle.decided_by_actor_id, None, cycle.decided_at)
        if cycle.status == "rejected":
            return _Found("rejected", cycle.decided_by_actor_id, None, cycle.decided_at)
    return None


def _wait(repos: BoardRepositories, card_id: str, since: str) -> _Found | None:
    """The first time since the question that a person cleared the wait or replaced it."""
    found: list[_Found] = []
    for action in ("card.wait_cleared", "card.wait_set"):
        entries = repos.activity.page(
            {"entity_type": "card", "entity_id": card_id, "action": action},
            limit=_ACTIVITY_PAGE,
            offset=0,
        )
        found += [
            _Found("cleared", entry.actor_id, None, entry.timestamp)
            for entry in entries
            if entry.timestamp >= since and entry.actor_type == "user"
        ]
    return min(found, key=lambda entry: entry.at, default=None)


def _confirmation(repos: BoardRepositories, card_id: str, since: str) -> _Found | None:
    card = repos.cards.get(card_id)
    if card is None or card.human_confirmed_at is None or card.human_confirmed_at < since:
        return None
    if card.human_confirmed_by_actor_id is None:
        return None
    return _Found("confirmed", card.human_confirmed_by_actor_id, None, card.human_confirmed_at)


def _found(
    repos: BoardRepositories,
    loop_id: str,
    decision: AskedDecision,
    card_id: str | None,
    subject: Mapping[str, JsonValue],
    since: str,
) -> _Found | None:
    match decision:
        case "analysis" | "roadmap":
            return _review(repos, loop_id, decision, subject, since)
        case "implementation":
            return _implementation(repos, loop_id, since)
        case "qa":
            return _qa(repos, loop_id, subject, since)
        case "wait":
            return None if card_id is None else _wait(repos, card_id, since)
        case "confirmation":
            return None if card_id is None else _confirmation(repos, card_id, since)


class DecisionOutcomeService:
    """Reads whether a person took a decision a key asked them for; it never takes one."""

    def __init__(self, store: BoardUnitOfWork, accounts: RegistryUnitOfWork) -> None:
        self.store = store
        self.accounts = accounts

    def taken(
        self,
        board_id: str,
        loop_id: str,
        decision: AskedDecision,
        *,
        card_id: str | None,
        subject: Mapping[str, JsonValue],
        since: str,
    ) -> DecisionTaken | None:
        """The decision on ``subject`` (what the question was about when it was asked) taken at
        or after ``since``, or None while nobody took it."""
        with self.store.reader(board_id) as repos:
            found = _found(repos, loop_id, decision, card_id, subject, since)
        if found is None:
            return None
        name = found.name
        if name is None:
            with self.accounts.reader() as registry:
                actor = registry.actors.many([found.actor_id]).get(found.actor_id)
            name = actor.name if actor is not None else None
        return {
            "outcome": found.outcome,
            "decided_by_id": found.actor_id,
            "decided_by": name,
            "decided_at": found.at,
        }


__all__ = [
    "ASKED_DECISIONS",
    "TICKET_DECISIONS",
    "AskedDecision",
    "DecisionOutcomeService",
    "DecisionTaken",
    "Outcome",
]
