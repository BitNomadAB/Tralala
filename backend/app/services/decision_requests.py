"""A question a key asked its person, and the decision that answers it: who, what and where.

When ``ask_person`` asks a person for a decision, the board records it: an activity row
``decision.requested`` on the Loop (a review, the implementation, QA) or on the Ticket (a wait, a
person's task), by the key's actor, whose changes say which decision, which key
(``credential_id``, ``key_name``), whose key it is (``owner_name``, the person who issued it) and
how the person was asked (``via``: ``link``, the person decides in Tralala at the decision's
address). A decision taken while such questions are open answers them all: its history row carries
``asked_through``, one ``{credential_id, key_name, via}`` per key, and a decision on a Ticket also
gets one comment by the person who decided that names those keys. A decision nobody asked for is
recorded as before, without ``asked_through`` and without a comment.

**When a question is open.** Everything is read from the board's own rows, never from a request:

- a key's question opens with its ``decision.requested`` row, one per decision, target (the Loop,
  or the Ticket) and key, so several keys, of one person or of several, each have their own;
- it is answered by the first decision on that decision and target recorded at or after the row
  (``last_decided``), whatever the outcome; every question open then is answered by it;
- it is withdrawn when the same key reports that its person declined or cancelled the question
  (a ``decision.request_closed`` row at or after it);
- it lapses ``OPEN_FOR`` (30 minutes, twice the life of a request state) after its row. A key that
  is still asking then (a retry with a state, or a new call) finds no open question and writes a
  new row, so a session that keeps asking keeps its question open, while one that went away stops
  counting: a decision taken a week after an abandoned question is not marked as asked.

While a key's question is open, asking again writes no row. Each row is written by
``DecisionRequestService`` in a writer of its own; the decision services call ``open_questions``
inside the decision's own unit of work, before they write the decision, and the comment goes
through the board repositories in that same unit of work, as plain text without ``@`` so no mention
job is ever queued.

``via`` is ``link`` for every question here. A decision taken another way later (in the editor,
through the key) is told apart by another ``via``, in the same rows.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final, TypedDict
from uuid import uuid4

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..db.generated.board import ActivityLogRow, CommentsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork
from .activity import activity_entry
from .decision_outcomes import TICKET_DECISIONS, AskedDecision
from .lists import BoardChecks
from .request_state import REQUEST_STATE_TTL

REQUESTED: Final = "decision.requested"
CLOSED: Final = "decision.request_closed"
# A question lapses this long after its row: twice the life of a request state, so a key that asks
# again with a state issued before the row lapsed still finds it open; one that went away does not.
OPEN_FOR: Final = 2 * REQUEST_STATE_TTL
VIA_LINK: Final = "link"
# The newest rows of one kind on one Loop or Ticket that are read; far more than one decision's
# questions in a window of thirty minutes.
_PAGE: Final = 200


class AskedThrough(TypedDict):
    """A key whose question a decision answers: its id, its name and how the person was asked."""

    credential_id: str
    key_name: str | None
    via: str


def target_of(decision: AskedDecision, loop_id: str, card_id: str | None) -> tuple[str, str]:
    """Where a decision's rows live: the Ticket for a wait or a confirmation, else the Loop."""
    if decision in TICKET_DECISIONS and card_id is not None:
        return "card", card_id
    return "loop", loop_id


def _changes(row: ActivityLogRow) -> dict[str, JsonValue]:
    try:
        changes: JsonValue = json.loads(row.changes_json or "{}")
    except ValueError:
        return {}
    return changes if isinstance(changes, dict) else {}


def _rows(repos: BoardRepositories, entity: tuple[str, str], action: str) -> list[ActivityLogRow]:
    entity_type, entity_id = entity
    return repos.activity.page(
        {"entity_type": entity_type, "entity_id": entity_id, "action": action},
        limit=_PAGE,
        offset=0,
    )


def _newest(values: Sequence[str | None]) -> str | None:
    found = [value for value in values if value is not None]
    return max(found, default=None)


def _newest_approval(repos: BoardRepositories, loop_id: str, scope: str) -> str | None:
    rows = [row for row in repos.approvals.newest_first(loop_id) if row.scope == scope]
    return rows[0].created_at if rows else None


def last_decided(
    repos: BoardRepositories, loop_id: str, decision: AskedDecision, card_id: str | None
) -> str | None:
    """When the newest decision of this kind on this target was recorded, or None."""
    match decision:
        case "analysis" | "roadmap" | "implementation":
            return _newest_approval(repos, loop_id, decision)
        case "qa":
            cycles = [cycle.decided_at for cycle in repos.qa.cycles(loop_id)]
            return _newest([_newest_approval(repos, loop_id, "qa"), *cycles])
        case "wait" | "confirmation":
            if card_id is None:
                return None
            card = ("card", card_id)
            if decision == "confirmation":
                confirmed = [row.timestamp for row in _rows(repos, card, "card.human_confirmed")]
                row = repos.cards.get(card_id)
                return _newest([*confirmed, row.human_confirmed_at if row else None])
            cleared = [row.timestamp for row in _rows(repos, card, "card.wait_cleared")]
            # A person who replaces a wait answers it as well; a key never replaces one.
            replaced = [
                row.timestamp
                for row in _rows(repos, card, "card.wait_set")
                if row.actor_type == "user"
            ]
            return _newest([*cleared, *replaced])


def _since(now: str) -> str:
    moment = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)
    return iso_utc(moment - OPEN_FOR)


def open_questions(
    repos: BoardRepositories,
    *,
    loop_id: str,
    decision: AskedDecision,
    card_id: str | None,
    now: str,
) -> list[AskedThrough]:
    """The keys whose question about ``decision`` on its target is open at ``now``, by the rule
    in the module docstring, oldest question first; one entry per key."""
    entity = target_of(decision, loop_id, card_id)
    since = _since(now)
    requests = [
        row
        for row in _rows(repos, entity, REQUESTED)
        if row.timestamp > since and _changes(row).get("decision") == decision
    ]
    if not requests:
        return []
    decided = last_decided(repos, loop_id, decision, card_id)
    closed = [
        (row.timestamp, _changes(row).get("credential_id"))
        for row in _rows(repos, entity, CLOSED)
        if _changes(row).get("decision") == decision
    ]
    found: dict[str, AskedThrough] = {}
    for row in sorted(requests, key=lambda entry: (entry.timestamp, entry.id)):
        changes = _changes(row)
        credential = changes.get("credential_id")
        if not isinstance(credential, str) or credential in found:
            continue
        if decided is not None and decided >= row.timestamp:
            continue
        if any(key == credential and at >= row.timestamp for at, key in closed):
            continue
        name = changes.get("key_name")
        via = changes.get("via")
        found[credential] = {
            "credential_id": credential,
            "key_name": name if isinstance(name, str) else None,
            "via": via if isinstance(via, str) else VIA_LINK,
        }
    return list(found.values())


def with_asked_through(
    changes: Mapping[str, object], through: Sequence[AskedThrough]
) -> dict[str, object]:
    """A decision's changes, with ``asked_through`` only when a question was open."""
    if not through:
        return dict(changes)
    return {**changes, "asked_through": [dict(entry) for entry in through]}


def _plain(name: str | None) -> str:
    """A key's name as plain text in a comment: never an ``@`` that could read as a mention."""
    cleaned = " ".join((name or "").replace("@", " at ").split())
    return cleaned or "(unnamed)"


def keys_text(through: Sequence[AskedThrough]) -> str:
    """``the key A``, ``the keys A and B``, ``the keys A, B and C``."""
    names = [_plain(entry["key_name"]) for entry in through]
    if len(names) == 1:
        return f"the key {names[0]}"
    return f"the keys {', '.join(names[:-1])} and {names[-1]}"


_ANSWERS: Final[dict[AskedDecision, str]] = {
    "wait": "cleared the wait on this Ticket",
    "confirmation": "confirmed that the person's task on this Ticket is done",
}


def answer_comment(person: str, decision: AskedDecision, through: Sequence[AskedThrough]) -> str:
    """What a decision on a Ticket that answers a question says on the Ticket: who decided, what,
    and that a coding session asked through which keys. Plain text, without ``@``."""
    what = _ANSWERS.get(decision, "decided")
    return (
        f"{_plain(person)} {what}. The question came from a coding session through "
        f"{keys_text(through)}."
    )


def add_answer_comment(
    repos: BoardRepositories,
    actor: ActorContext,
    card_id: str,
    decision: AskedDecision,
    through: Sequence[AskedThrough],
    *,
    new_id: Callable[[], str],
    now: str,
) -> None:
    """The one comment a decision on a Ticket that answers a question writes, by the person who
    decided, inside the decision's unit of work; nothing when no question was open."""
    if not through:
        return
    repos.comments.add(
        CommentsRow(
            id=new_id(),
            card_id=card_id,
            actor_id=actor.actor_id,
            content=answer_comment(actor.actor_name, decision, through),
            created_at=now,
            updated_at=now,
        )
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class DecisionRequestService:
    """Records that a key asked its person for a decision, and that the person declined or
    cancelled the question; it takes no decision."""

    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        accounts: RegistryUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.accounts = accounts
        self._clock = clock
        self._new_id = new_id

    def _key(self, credential_id: str) -> tuple[str | None, str | None]:
        """The key's name and the name of the person who issued it."""
        with self.accounts.reader() as registry:
            issued = registry.credentials.get(credential_id)
        if issued is None:
            return None, None
        return issued.credential.name, issued.owner_name

    def _write(
        self,
        actor: ActorContext,
        board_id: str,
        target: tuple[str, AskedDecision, str | None],
        *,
        action: str,
        extra: Mapping[str, object],
        when_open: bool,
    ) -> bool:
        credential_id = actor.credential_id
        if credential_id is None:  # only a key asks; a session cookie has no key to name
            return False
        loop_id, decision, card_id = target
        key_name, owner_name = self._key(credential_id)
        now = iso_utc(self._clock())
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            asking = open_questions(
                repos, loop_id=loop_id, decision=decision, card_id=card_id, now=now
            )
            is_open = any(entry["credential_id"] == credential_id for entry in asking)
            if is_open != when_open:
                return False
            entity_type, entity_id = target_of(decision, loop_id, card_id)
            repos.activity.add(
                activity_entry(
                    actor,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    changes={
                        "decision": decision,
                        "credential_id": credential_id,
                        "key_name": key_name,
                        "owner_name": owner_name,
                        **extra,
                    },
                    entry_id=self._new_id(),
                    timestamp=now,
                )
            )
        return True

    def asked(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        decision: AskedDecision,
        card_id: str | None,
    ) -> bool:
        """Record the key's question unless it already has one open; True when a row was
        written."""
        return self._write(
            actor,
            board_id,
            (loop_id, decision, card_id),
            action=REQUESTED,
            extra={"via": VIA_LINK},
            when_open=False,
        )

    def withdrawn(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        decision: AskedDecision,
        card_id: str | None,
        reason: str,
    ) -> bool:
        """Record that the key's person declined or cancelled its open question (``reason``), so
        a later decision does not answer it; True when a row was written."""
        return self._write(
            actor,
            board_id,
            (loop_id, decision, card_id),
            action=CLOSED,
            extra={"reason": reason},
            when_open=True,
        )


__all__ = [
    "CLOSED",
    "OPEN_FOR",
    "REQUESTED",
    "VIA_LINK",
    "AskedThrough",
    "DecisionRequestService",
    "add_answer_comment",
    "answer_comment",
    "keys_text",
    "last_decided",
    "open_questions",
    "target_of",
    "with_asked_through",
]
