from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from typing import Protocol
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailure
from ..db.generated.board import (
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionThreadsRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from .activity import activity_entry
from .agents import RoleSnapshot
from .discussion_answers import read_answer
from .discussion_inbox import InboxPage, decided_by, read_inbox
from .discussion_synthesis import latest_answers, positions, read_synthesis
from .events import HUMAN_REVIEW_COMPLETED, MESSAGE_CREATED, STATUS_CHANGED, Event, EventService
from .loops import ensure_ticket_writable
from .mentions import extract_mentions
from .runs import RunEntry, RunService, recent_runs

REVIEW_DECISIONS = {"approve": "approved", "veto": "vetoed", "rework": "rework_requested"}
# A human message starts one round in these modes; manual threads wait for an explicit run.
AUTO_RUN_MODES = frozenset({"roundtable", "autonomous"})
AGENT_TRIGGER = re.compile(r"(?<![\w.-])@agents?\b", re.IGNORECASE)

DiscussionEntry = dict[str, object]
"""A thread as the API answers it: its columns plus counts, its ticket and, in detail, its
participants, messages (each with its structured ``answer``), the newest round's ``synthesis``,
each participant's current ``positions``, the votes and the runs."""


class BoardChecks(Protocol):
    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


class RoleSnapshots(Protocol):
    def role_snapshot(self, agent_id: str) -> RoleSnapshot: ...


def requests_agent_reply(content: str, participants: Sequence[Mapping[str, object]]) -> bool:
    """`@agents` or a participant's name asks the thread to answer, whatever the mode."""
    if AGENT_TRIGGER.search(content):
        return True
    names = [
        {"id": str(participant["participant_id"]), "name": str(participant["display_name"])}
        for participant in participants
    ]
    return bool(extract_mentions(content, names))


def _new_id() -> str:
    return str(uuid4())


def _thread(repos: BoardRepositories, discussion_id: str) -> DiscussionThreadsRow:
    thread = repos.threads.get(discussion_id)
    if thread is None:
        raise NotFound("Discussion not found")
    return thread


def message_entry(row: DiscussionMessagesRow) -> dict[str, object]:
    """A message as the API answers it: its columns, with the stored answer read as ``answer``."""
    entry: dict[str, object] = dict(asdict(row))
    entry.pop("answer_json", None)
    entry["answer"] = read_answer(row.answer_json)
    return entry


def detail(repos: BoardRepositories, thread: DiscussionThreadsRow) -> DiscussionEntry:
    """What a thread's detail adds to its columns: who takes part, what was said and where each
    participant stands, the decision support of the newest round, and the runs."""
    participants = repos.participants.for_thread(thread.id)
    messages = repos.messages.for_thread(thread.id)
    newest = repos.rounds.newest_for_thread(thread.id)
    synthesis: dict[str, object] | None = None
    if newest is not None:
        stored = read_synthesis(newest.synthesis_json)
        synthesis = None if stored is None else {**stored, "round_id": newest.id}
    runs: list[RunEntry] = recent_runs(repos, thread.id)
    return {
        "participants": [asdict(row) for row in participants],
        "messages": [message_entry(row) for row in messages],
        "positions": positions(participants, latest_answers(messages, participants)),
        "synthesis": synthesis,
        "votes": repos.votes.with_names(thread.id),
        "runs": runs,
        "active_run": next((run for run in runs if run["status"] in {"running", "paused"}), None),
    }


def serialize(
    repos: BoardRepositories, thread: DiscussionThreadsRow, *, with_detail: bool = False
) -> DiscussionEntry:
    entry: DiscussionEntry = dict(asdict(thread))
    entry["participant_count"] = repos.participants.count(thread.id)
    entry["message_count"] = repos.messages.count(thread.id)
    card = repos.cards.get(thread.card_id) if thread.card_id is not None else None
    loop = repos.loops.get(card.loop_id) if card is not None and card.loop_id else None
    # The ticket is read with its Loop joined, so a card without a Loop reads as no ticket.
    joined = card is not None and loop is not None
    entry["card_title"] = card.title if joined and card else None
    entry["ticket_key"] = card.ticket_key if joined and card else None
    entry["loop_id"] = card.loop_id if joined and card else None
    entry["loop_key"] = loop.key if joined and loop else None
    entry["loop_name"] = loop.name if joined and loop else None
    entry["round_count"] = thread.round_count
    entry["tokens_used"] = thread.tokens_used
    entry["elapsed_ms"] = thread.elapsed_ms
    entry["run_state"] = thread.run_state or "idle"
    entry["decided_by_name"] = decided_by(repos.outcomes.newest(thread.id))
    if with_detail:
        entry.update(detail(repos, thread))
    return entry


class DiscussionService:
    """Ticket-bound discussions. Participants keep an immutable role snapshot."""

    def __init__(
        self,
        board_service: BoardChecks,
        agent_service: RoleSnapshots,
        store: BoardUnitOfWork,
        registry: RegistryUnitOfWork,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.board_service = board_service
        self.agent = agent_service
        self.store = store
        self.registry = registry
        self._clock = clock
        self._new_id = new_id
        self.runs: RunService | None = None
        self.events: EventService | None = None

    def _record(
        self,
        repos: BoardRepositories,
        discussion_id: str,
        type: str,
        payload: Mapping[str, object],
        actor: ActorContext | None = None,
    ) -> Event | None:
        if self.events is None:
            return None
        return self.events.record(
            repos, discussion_id=discussion_id, type=type, payload=payload, actor=actor
        )

    def _publish(self, board_id: str, *events: Event | None) -> None:
        if self.events is None:
            return
        for event in events:
            if event is not None:
                self.events.publish(board_id, event)

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        card_id: str | None,
        changes: Mapping[str, object],
        now: str,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type="card",
                entity_id=card_id or "",
                changes=changes,
                entry_id=self._new_id(),
                timestamp=now,
            )
        )

    def review(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> DiscussionEntry:
        """Human-only final decision. Approving never executes ticket changes."""
        actor.require("discussions:admin")
        if not actor.is_user:
            raise Forbidden("Only a human reviewer can decide a discussion")
        target = REVIEW_DECISIONS.get(decision)
        if target is None:
            raise ValidationFailure("Unknown review decision", details={"decision": decision})
        if decision in {"veto", "rework"} and not reason.strip():
            raise ValidationFailure(
                "An explanation is required for this decision", details={"field": "reason"}
            )
        self.board_service.ensure_active(board_id)
        now = self._clock()
        with self.store.writer(board_id) as repos:
            thread = _thread(repos, discussion_id)
            if thread.status in {"approved", "vetoed", "cancelled"}:
                raise Conflict("Discussion is already closed", details={"status": thread.status})
            if repos.runs.active(discussion_id) is not None:
                raise Conflict("A run is still active; stop it before reviewing")
            if thread.status not in {"consensus_proposed", "human_review", "discussing"}:
                raise Conflict(
                    "Discussion is not ready for review", details={"status": thread.status}
                )
            repos.threads.decide(discussion_id, target, now=now)
            stated = reason.strip()
            repos.outcomes.add(
                DiscussionOutcomesRow(
                    id=self._new_id(),
                    discussion_id=discussion_id,
                    summary=f"{decision} by {actor.actor_name}" + (f": {stated}" if stated else ""),
                    payload_json=json.dumps(
                        {
                            "decision": decision,
                            "reason": stated,
                            "actor_id": actor.actor_id,
                            "actor_name": actor.actor_name,
                        }
                    ),
                    created_at=now,
                )
            )
            self._log(
                repos,
                actor,
                "discussion.reviewed",
                thread.card_id,
                {"discussion_id": discussion_id, "decision": decision},
                now,
            )
            review_event = self._record(
                repos,
                discussion_id,
                HUMAN_REVIEW_COMPLETED,
                {"decision": decision, "reason": stated, "status": target},
                actor,
            )
            status_event = self._record(
                repos, discussion_id, STATUS_CHANGED, {"status": target, "run_state": "idle"}, actor
            )
        self._publish(board_id, review_event, status_event)
        return self.get(board_id, discussion_id)

    # --- queries -------------------------------------------------------------

    def list(
        self,
        board_id: str,
        *,
        status: str | None = None,
        card_id: str | None = None,
        limit: int = 50,
    ) -> list[DiscussionEntry]:
        """The board's threads by most recent activity, optionally in one status or on one
        Ticket (its Discussions tab)."""
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            threads = repos.threads.newest(
                status=status or None, card_id=card_id or None, limit=limit
            )
            return [serialize(repos, thread) for thread in threads]

    def get(self, board_id: str, discussion_id: str) -> DiscussionEntry:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return serialize(repos, _thread(repos, discussion_id), with_detail=True)

    def inbox(self, actor: ActorContext) -> InboxPage:
        """What waits for the person across every board that is not archived: the threads that
        wait for a decision, the ones the agents are talking in and the decided ones
        (``discussion_inbox``). It names the boards, so it needs ``boards:read`` beside
        ``discussions:read``."""
        actor.require("boards:read")
        actor.require("discussions:read")
        return read_inbox(self.registry, self.store)

    # --- commands ------------------------------------------------------------

    def create(
        self, actor: ActorContext, board_id: str, payload: DiscussionCreate
    ) -> DiscussionEntry:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        now = self._clock()
        discussion_id = self._new_id()
        with self.store.writer(board_id) as repos:
            card = repos.cards.get(payload.card_id)
            if card is None or card.archived_at is not None:
                raise ValidationFailure(
                    "Discussion must reference an existing ticket",
                    details={"card_id": payload.card_id},
                )
            ensure_ticket_writable(repos, payload.card_id)
            title = (payload.title or f"{card.title} — discussion").strip()
            snapshots = self._snapshots(payload.participant_ids)
            repos.threads.add(
                DiscussionThreadsRow(
                    id=discussion_id,
                    card_id=payload.card_id,
                    title=title,
                    goal=payload.goal,
                    mode=payload.mode,
                    status="open",
                    created_by_actor_id=actor.actor_id,
                    created_by_type=actor.actor_type,
                    created_by_name=actor.actor_name,
                    max_rounds=payload.max_rounds,
                    origin_comment_id=None,
                    escalation_depth=0,
                    created_at=now,
                    updated_at=now,
                    last_activity_at=now,
                    round_count=0,
                    run_state="idle",
                    tokens_used=0,
                    elapsed_ms=0,
                )
            )
            for snapshot in snapshots:
                repos.participants.add(
                    DiscussionParticipantsRow(
                        id=self._new_id(),
                        discussion_id=discussion_id,
                        participant_id=snapshot["agent_id"],
                        participant_type="agent",
                        display_name=snapshot["agent_name"],
                        role_template_id=snapshot["role_template_id"],
                        role_template_name=snapshot["role_template_name"],
                        role_template_updated_at=snapshot["role_template_updated_at"],
                        role_source=snapshot["role_source"],
                        system_prompt=snapshot["system_prompt"],
                        system_prompt_sha256=snapshot["system_prompt_sha256"],
                        snapshot_at=now,
                        joined_at=now,
                    )
                )
            repos.messages.add(
                DiscussionMessagesRow(
                    id=self._new_id(),
                    discussion_id=discussion_id,
                    parent_message_id=None,
                    author_actor_id=actor.actor_id,
                    author_type=actor.actor_type,
                    author_name=actor.actor_name,
                    author_role=None,
                    content=payload.goal,
                    status="posted",
                    model=None,
                    created_at=now,
                    deleted_at=None,
                    round_number=0,
                    content_sha256=None,
                    answer_json="{}",
                )
            )
            self._log(
                repos,
                actor,
                "discussion.created",
                payload.card_id,
                {"discussion_id": discussion_id, "title": title},
                now,
            )
        return self.get(board_id, discussion_id)

    def _snapshots(self, participant_ids: list[str]) -> list[RoleSnapshot]:
        """Each participant's role as it is now; only an enabled agent may take part."""
        snapshots: list[RoleSnapshot] = []
        for participant_id in participant_ids:
            with self.registry.reader() as registry:
                agent = registry.agents.get(participant_id)
            if agent is None or not agent.enabled:
                raise ValidationFailure(
                    "Participant must be an enabled agent",
                    details={"participant_id": participant_id},
                )
            snapshot = self.agent.role_snapshot(agent.id)
            snapshots.append({**snapshot, "agent_id": agent.id, "agent_name": agent.name})
        return snapshots

    def add_message(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        payload: DiscussionMessageCreate,
    ) -> DiscussionEntry:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        now = self._clock()
        with self.store.writer(board_id) as repos:
            thread = _thread(repos, discussion_id)
            if payload.parent_message_id and not repos.messages.belongs(
                payload.parent_message_id, discussion_id
            ):
                raise ValidationFailure("Parent message does not belong to this discussion")
            message_id = self._new_id()
            repos.messages.add(
                DiscussionMessagesRow(
                    id=message_id,
                    discussion_id=discussion_id,
                    parent_message_id=payload.parent_message_id,
                    author_actor_id=actor.actor_id,
                    author_type=actor.actor_type,
                    author_name=actor.actor_name,
                    author_role=None,
                    content=payload.content,
                    status="posted",
                    model=None,
                    created_at=now,
                    deleted_at=None,
                    round_number=0,
                    content_sha256=None,
                    answer_json="{}",
                )
            )
            repos.threads.note_message(discussion_id, now=now)
            self._log(
                repos,
                actor,
                "discussion.message_posted",
                thread.card_id,
                {"discussion_id": discussion_id, "message_id": message_id},
                now,
            )
            participants: list[Mapping[str, object]] = [
                {"participant_id": row.participant_id, "display_name": row.display_name}
                for row in repos.participants.for_thread(discussion_id)
            ]
            message_event = self._record(
                repos,
                discussion_id,
                MESSAGE_CREATED,
                {
                    "message_id": message_id,
                    "parent_message_id": payload.parent_message_id,
                    "author_actor_id": actor.actor_id,
                    "author_type": actor.actor_type,
                    "author_name": actor.actor_name,
                    "content": payload.content,
                },
                actor,
            )
        self._publish(board_id, message_event)
        auto_run = self._auto_run(
            actor, board_id, discussion_id, thread.mode, payload.content, participants
        )
        detail = self.get(board_id, discussion_id)
        detail["auto_run"] = auto_run
        return detail

    def _auto_run(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        mode: str,
        content: str,
        participants: Sequence[Mapping[str, object]],
    ) -> str | None:
        """Answer a human message automatically when the thread asks for it.

        In roundtable/autonomous threads every human message starts one background round. In a
        manual thread the message must opt in with `@agents` or a participant's name. One round is
        the least surprising spend; a thread that is closed or already running keeps the message,
        and the post itself never fails because no run could be started. Returns what happened so
        the client can explain a skipped answer.
        """
        if self.runs is None or not actor.is_user:
            return None
        if mode not in AUTO_RUN_MODES and not requests_agent_reply(content, participants):
            return None
        try:
            self.runs.start(
                actor, board_id, discussion_id, rounds=1, autonomous=False, background=True
            )
        except Conflict as exc:
            details: Mapping[str, object] = exc.details or {}
            return "already_running" if details.get("run_id") else "thread_closed"
        except ValidationFailure:
            return "no_participants"
        return "started"
