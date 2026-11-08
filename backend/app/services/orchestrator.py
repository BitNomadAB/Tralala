"""Discussion round engine: one bounded round of agent answers in the standard shape.

Each participant answers with a ``DiscussionAnswer`` (``discussion_answers``), asked and repaired by
``discussion_ask``; the prose is the message's ``content`` and the structure its ``answer_json``.
The engine never decides whether another round should follow; ``RunService`` owns the loop, the
budgets and the run record.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Protocol, TypedDict
from uuid import uuid4

from ..core.dates import utcnow
from ..core.errors import NotFound
from ..db.generated.board import (
    DiscussionMessagesRow,
    DiscussionParticipantsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.registry import RegistryUnitOfWork
from . import runtime
from .discussion_answers import GO, answer_instructions, answer_line, read_answer
from .discussion_ask import AnswerCall, AnswerFor, ask_participant
from .discussion_ask import usage_tokens as usage_tokens  # mentions and the tests read it here
from .events import (
    AGENT_COMPLETED,
    AGENT_FAILED,
    AGENT_STARTED,
    MESSAGE_CREATED,
    VOTE_RECORDED,
    Event,
    EventService,
)


class AgentCall(Protocol):
    """``runtime.call_agent``: one answer from an agent with a verdict read from its text, as a
    ticket comment's mention asks for it."""

    def __call__(
        self,
        settings: object,
        agent_row: dict[str, object],
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> Mapping[str, object]: ...


class Failure(TypedDict):
    agent: str
    error: str


class Position(TypedDict):
    participant_id: str
    position: str


class RoundOutcome(TypedDict):
    round_number: int
    answers: int
    repeats: int
    failures: list[Failure]
    tokens: int
    elapsed_ms: int
    interrupted: str | None
    budget_hit: bool
    unanimous: bool
    participants: int
    latest_positions: list[Position]
    card_id: str | None


def content_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def ticket_briefing(repos: BoardRepositories, card_id: str | None) -> str:
    """Which ticket the thread is about, as the prompt names it.

    A card gets its key when a plan is published, so a thread on an unplanned ticket names the id
    instead. Either way the agent is told which ticket it is looking at.
    """
    card = repos.cards.get(card_id) if card_id is not None else None
    if card is None:
        return "Ticket: (missing)"
    loop = repos.loops.get(card.loop_id)
    loop_name = loop.name if loop is not None and loop.name else "(unknown)"
    loop_key = loop.key if loop is not None and loop.key else "no key"
    return (
        f"Loop: {loop_name} ({loop_key})\n"
        f"Ticket: {card.title}\n"
        f"Ticket id: {card.id} (key: {card.ticket_key or 'not keyed yet'})\n"
        f"Priority: {card.priority}\n"
        f"Description:\n{(card.description or '(empty)')[:4000]}"
    )


def quoted(author: str, author_type: str, line: str, content: str) -> str:
    """One message as a prompt quotes it: the answer's one line first, then the prose."""
    lead = f"[{author} · {author_type}]"
    return f"{lead} {line}\n{content[:1500]}" if line else f"{lead} {content[:1500]}"


def transcript(repos: BoardRepositories, discussion_id: str, limit: int = 20) -> str:
    """The thread's latest messages, oldest first, as the prompt quotes them."""
    history = list(reversed(repos.messages.newest(discussion_id, limit=limit)))
    return "\n\n".join(
        quoted(
            entry.author_name,
            entry.author_type,
            answer_line(read_answer(entry.answer_json)),
            entry.content,
        )
        for entry in history
    )


def prompt(
    ticket: str, thread: DiscussionThreadsRow, history: str, in_round: list[str]
) -> dict[str, str]:
    sections = [ticket, f"Discussion goal: {thread.goal}"]
    sections.append(f"Transcript so far:\n{history or '(nothing yet)'}")
    if in_round:
        # Agents answer one after another, so each one can respond to what was just said instead of
        # everyone replying to the previous round in parallel.
        sections.append("Answers earlier in this round, before yours:\n" + "\n\n".join(in_round))
    sections.append(answer_instructions())
    return {"role": "user", "content": "\n\n".join(sections)}


def is_unanimous(
    latest: Mapping[str, str],
    participants: list[DiscussionParticipantsRow],
    *,
    mode: str,
    prior_answers: int,
    answers: int,
    repeats: int,
) -> bool:
    """Whether the latest positions are a fresh agreement of every participant to go ahead."""
    # In a roundtable the agents are meant to review each other, so agreement in the opening round
    # cannot be consensus: whoever answered first had read nobody.
    needs_review_round = mode == "roundtable" and len(participants) > 1
    # A round in which every agent repeated its previous text produced no new argument, so the
    # existing votes cannot be read as a fresh agreement.
    only_repeats = repeats > 0 and answers == 0
    return (
        bool(latest)
        and set(latest.values()) <= GO
        and set(latest) == {p.participant_id for p in participants}
        and (not needs_review_round or prior_answers > 0)
        and not only_repeats
    )


def _new_id() -> str:
    return str(uuid4())


class Orchestrator:
    """Runs one bounded round per participant and records explicit positions."""

    def __init__(
        self,
        settings: object,
        store: BoardUnitOfWork,
        registry: RegistryUnitOfWork,
        events: EventService | None = None,
        *,
        call_completion: AnswerCall = runtime.call_completion,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.store = store
        self.registry = registry
        self.events = events
        self._call_completion = call_completion
        self._clock = clock
        self._new_id = new_id
        self._monotonic = monotonic

    def _run_state(self, board_id: str, run_id: str) -> tuple[str, int]:
        with self.store.reader(board_id) as repos:
            run = repos.runs.get(run_id)
        if run is None:
            raise NotFound("Discussion run not found")
        return run.status, run.tokens_used

    def _emit(self, board_id: str, event: Event | None) -> None:
        if event is not None and self.events is not None:
            self.events.publish(board_id, event)

    def _record(
        self, repos: BoardRepositories, discussion_id: str, type: str, payload: Mapping[str, object]
    ) -> Event | None:
        if self.events is None:
            return None
        return self.events.record(repos, discussion_id=discussion_id, type=type, payload=payload)

    def run_round(
        self,
        board_id: str,
        discussion_id: str,
        *,
        run_id: str,
        round_number: int,
        token_budget: int | None,
    ) -> RoundOutcome:
        """Execute one round and report what happened; the caller decides what comes next."""
        started = self._monotonic()
        with self.store.reader(board_id) as repos:
            thread = repos.threads.get(discussion_id)
            if thread is None:
                raise NotFound("Discussion not found")
            participants = repos.participants.for_thread(discussion_id)
            ticket = ticket_briefing(repos, thread.card_id)
            history = transcript(repos, thread.id)
            # Counted before the round runs: a roundtable may only conclude once some earlier round
            # produced answers, otherwise a unanimous first round means everyone guessed alike.
            prior_answers = repos.messages.agent_answers(discussion_id)

        _, tokens_before = self._run_state(board_id, run_id)
        answers = 0
        repeats = 0
        tokens = 0
        failures: list[Failure] = []
        interrupted: str | None = None
        budget_hit = False
        in_round: list[str] = []

        for participant in participants:
            messages = [prompt(ticket, thread, history, in_round)]
            status, _ = self._run_state(board_id, run_id)
            if status != "running":
                interrupted = status
                break
            with self.registry.reader() as registry:
                agent = registry.agents.get(participant.participant_id)
            if agent is None:
                failures.append({"agent": participant.display_name, "error": "agent_missing"})
                continue
            identity = {
                "participant_id": participant.participant_id,
                "agent": participant.display_name,
                "round_number": round_number,
            }
            with self.store.writer(board_id) as repos:
                started_event = self._record(repos, discussion_id, AGENT_STARTED, identity)
            self._emit(board_id, started_event)
            call_started = self._monotonic()
            asked = ask_participant(
                self._call_completion,
                self.settings,
                asdict(agent),
                system_prompt=participant.system_prompt,
                messages=messages,
                about=AnswerFor(discussion_id, participant.participant_id, round_number),
            )
            duration_ms = int((self._monotonic() - call_started) * 1000)
            if not asked["ok"]:
                error = str(asked["error"])
                failures.append({"agent": participant.display_name, "error": error})
                with self.store.writer(board_id) as repos:
                    failed_event = self._record(
                        repos,
                        discussion_id,
                        AGENT_FAILED,
                        {**identity, "error": error, "duration_ms": duration_ms},
                    )
                self._emit(board_id, failed_event)
                continue
            answer = asked["content"]
            structured = asked["answer"]
            verdict = structured["position"]
            model = asked["model"]
            in_round.append(
                quoted(participant.display_name, "agent", answer_line(structured), answer)
            )
            digest = content_hash(answer)
            round_tokens = asked["tokens"]
            tokens += round_tokens
            now = self._clock()
            message_event: Event | None = None
            vote_event: Event | None = None
            with self.store.writer(board_id) as repos:
                previous = repos.messages.last_digest(discussion_id, participant.participant_id)
                if previous is not None and previous == digest:
                    repeats += 1
                else:
                    message_id = self._new_id()
                    repos.messages.add(
                        DiscussionMessagesRow(
                            id=message_id,
                            discussion_id=discussion_id,
                            parent_message_id=None,
                            author_actor_id=participant.participant_id,
                            author_type="agent",
                            author_name=participant.display_name,
                            author_role=participant.role_template_name,
                            content=answer,
                            status="posted",
                            model=model,
                            created_at=now,
                            deleted_at=None,
                            round_number=round_number,
                            content_sha256=digest,
                            answer_json=json.dumps(structured),
                        )
                    )
                    message_event = self._record(
                        repos,
                        discussion_id,
                        MESSAGE_CREATED,
                        {
                            "message_id": message_id,
                            "author_actor_id": participant.participant_id,
                            "author_type": "agent",
                            "author_name": participant.display_name,
                            "author_role": participant.role_template_name,
                            "round_number": round_number,
                            "model": model,
                            "position": verdict,
                            "answer": structured,
                            "content": answer,
                        },
                    )
                    previous_position = repos.votes.latest_position(
                        discussion_id, participant.participant_id
                    )
                    if previous_position != verdict:
                        repos.votes.add(
                            DiscussionVotesRow(
                                id=self._new_id(),
                                discussion_id=discussion_id,
                                participant_id=participant.participant_id,
                                position=verdict,
                                justification=structured["recommendation"]
                                or "Answered in prose only.",
                                created_at=now,
                                round_number=round_number,
                            )
                        )
                        vote_event = self._record(
                            repos,
                            discussion_id,
                            VOTE_RECORDED,
                            {
                                "participant_id": participant.participant_id,
                                "agent": participant.display_name,
                                "position": verdict,
                                "round_number": round_number,
                            },
                        )
                    answers += 1
                repos.runs.add_tokens(run_id, round_tokens)
                completed_event = self._record(
                    repos,
                    discussion_id,
                    AGENT_COMPLETED,
                    {
                        **identity,
                        "position": verdict,
                        "format": structured["format"],
                        "repairs": asked["repairs"],
                        "tokens": round_tokens,
                        "duplicate": message_event is None,
                        "duration_ms": duration_ms,
                    },
                )
            self._emit(board_id, message_event)
            self._emit(board_id, vote_event)
            self._emit(board_id, completed_event)
            if token_budget is not None and tokens_before + tokens > token_budget:
                budget_hit = True
                break

        with self.store.reader(board_id) as repos:
            votes = repos.votes.newest_first(discussion_id)
        latest: dict[str, str] = {}
        for vote in votes:
            latest.setdefault(vote.participant_id, vote.position)
        unanimous = is_unanimous(
            latest,
            participants,
            mode=thread.mode,
            prior_answers=prior_answers,
            answers=answers,
            repeats=repeats,
        )
        return {
            "round_number": round_number,
            "answers": answers,
            "repeats": repeats,
            "failures": failures,
            "tokens": tokens,
            "elapsed_ms": int((self._monotonic() - started) * 1000),
            "interrupted": interrupted,
            "budget_hit": budget_hit,
            "unanimous": unanimous,
            "participants": len(participants),
            "latest_positions": [
                {"participant_id": key, "position": value} for key, value in latest.items()
            ],
            "card_id": thread.card_id,
        }
