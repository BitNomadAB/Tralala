"""How a round ends a discussion run, and the writes that record a round and a run's end.

``RunService`` reads the run, asks the engine for one round and opens the board unit of work; the
functions here take the open repositories, the time, the id source and the event service, write in
the order the service always did, and return the events to publish once the write is committed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from ..core.context import ActorContext
from ..db.generated.board import DiscussionOutcomesRow, DiscussionRoundsRow, DiscussionRunsRow
from ..repositories.board import BoardRepositories
from .activity import activity_entry
from .discussion_synthesis import RoundSynthesis, latest_answers, synthesize
from .events import (
    CONSENSUS_PROPOSED,
    ROUND_COMPLETED,
    RUN_FINISHED,
    STATUS_CHANGED,
    Event,
    EventService,
)
from .orchestrator import RoundOutcome
from .runs_views import require_run


def classify(run: DiscussionRunsRow, outcome: RoundOutcome) -> tuple[str, str | None]:
    """How a round ends the run, if it does: the run status and the reason."""
    if outcome["interrupted"] in {"stopped", "paused"}:
        return str(outcome["interrupted"]), str(outcome["interrupted"])
    if outcome["answers"] == 0 and len(outcome["failures"]) >= outcome["participants"]:
        return "failed", "all_participants_failed"
    if outcome["answers"] == 0 and outcome["repeats"]:
        return "no_progress", "duplicate_answers"
    if outcome["budget_hit"]:
        return "budget_exhausted", "token_budget"
    if outcome["unanimous"]:
        return "completed", "consensus"
    elapsed = run.elapsed_ms + outcome["elapsed_ms"]
    budget = run.time_budget_seconds
    if budget is not None and elapsed > budget * 1000:
        return "budget_exhausted", "time_budget"
    return "completed", None


def time_exhausted(run: DiscussionRunsRow) -> bool:
    budget = run.time_budget_seconds
    if budget is None:
        return False
    return run.elapsed_ms > budget * 1000


def started_by(run: DiscussionRunsRow) -> ActorContext:
    return ActorContext(
        actor_id=run.started_by_actor_id,
        actor_type=run.started_by_type,
        actor_name=run.started_by_name,
        scopes=frozenset({"discussions:write"}),
    )


def record_event(
    events: EventService | None,
    repos: BoardRepositories,
    discussion_id: str,
    type: str,
    payload: Mapping[str, object],
    actor: ActorContext | None = None,
) -> Event | None:
    if events is None:
        return None
    return events.record(
        repos, discussion_id=discussion_id, type=type, payload=payload, actor=actor
    )


def log_run_activity(
    repos: BoardRepositories,
    actor: ActorContext,
    action: str,
    discussion_id: str,
    changes: Mapping[str, object],
    now: str,
    *,
    new_id: Callable[[], str],
) -> None:
    repos.activity.add(
        activity_entry(
            actor,
            action=action,
            entity_type="discussion",
            entity_id=discussion_id,
            changes=changes,
            entry_id=new_id(),
            timestamp=now,
        )
    )


def round_synthesis(
    repos: BoardRepositories, discussion_id: str, round_number: int
) -> RoundSynthesis:
    """The decision support for the thread as the round leaves it, from each participant's latest
    answer; the thread's round count names the round across runs."""
    participants = repos.participants.for_thread(discussion_id)
    latest = latest_answers(repos.messages.for_thread(discussion_id), participants)
    thread = repos.threads.get(discussion_id)
    thread_round = (thread.round_count if thread is not None else 0) + 1
    return synthesize(
        participants, latest, round_number=round_number, thread_round=thread_round
    )


def record_round(
    repos: BoardRepositories,
    discussion_id: str,
    run: DiscussionRunsRow,
    outcome: RoundOutcome,
    status: str,
    *,
    now: str,
    new_id: Callable[[], str],
    events: EventService | None,
) -> tuple[Event | None, Event | None, Event | None]:
    """Store a finished round on its run and thread with its decision support; the round, status
    and consensus events."""
    thread_status = "consensus_proposed" if outcome["unanimous"] else "discussing"
    failures = len(outcome["failures"])
    synthesis = round_synthesis(repos, discussion_id, outcome["round_number"])
    repos.rounds.add(
        DiscussionRoundsRow(
            id=new_id(),
            discussion_id=discussion_id,
            run_id=run.id,
            round_number=outcome["round_number"],
            status=status,
            answers=outcome["answers"],
            failures=failures,
            repeats=outcome["repeats"],
            tokens_used=outcome["tokens"],
            elapsed_ms=outcome["elapsed_ms"],
            created_at=now,
            finished_at=now,
            synthesis_json=json.dumps(synthesis),
        )
    )
    repos.runs.record_round(
        run.id, round_number=outcome["round_number"], elapsed_ms=outcome["elapsed_ms"]
    )
    repos.threads.record_round(
        discussion_id,
        status=thread_status,
        tokens=outcome["tokens"],
        elapsed_ms=outcome["elapsed_ms"],
        now=now,
    )
    if outcome["unanimous"]:
        repos.outcomes.add(
            DiscussionOutcomesRow(
                id=new_id(),
                discussion_id=discussion_id,
                summary="Every participant supports going ahead.",
                payload_json=json.dumps({"synthesis": synthesis}),
                created_at=now,
            )
        )
    round_event = record_event(
        events,
        repos,
        discussion_id,
        ROUND_COMPLETED,
        {
            "run_id": run.id,
            "round_number": outcome["round_number"],
            "status": status,
            "answers": outcome["answers"],
            "repeats": outcome["repeats"],
            "failures": failures,
            "tokens_used": outcome["tokens"],
            "elapsed_ms": outcome["elapsed_ms"],
            "synthesis": synthesis,
        },
    )
    status_event = record_event(
        events,
        repos,
        discussion_id,
        STATUS_CHANGED,
        {
            "status": thread_status,
            "run_state": "running",
            "run_id": run.id,
            "round_number": outcome["round_number"],
        },
    )
    consensus_event = (
        record_event(
            events,
            repos,
            discussion_id,
            CONSENSUS_PROPOSED,
            {"run_id": run.id, "round_number": outcome["round_number"]},
        )
        if outcome["unanimous"]
        else None
    )
    log_run_activity(
        repos,
        started_by(run),
        "discussion.round_completed",
        discussion_id,
        {
            "run_id": run.id,
            "round": outcome["round_number"],
            "answers": outcome["answers"],
            "repeats": outcome["repeats"],
            "failures": failures,
            "status": status,
        },
        now,
        new_id=new_id,
    )
    return round_event, status_event, consensus_event


def finish_run(
    repos: BoardRepositories,
    discussion_id: str,
    run_id: str,
    status: str,
    reason: str | None,
    *,
    now: str,
    new_id: Callable[[], str],
    events: EventService | None,
    run_states: Mapping[str, str],
) -> tuple[Event | None, ...]:
    """End (or pause) the run; the events to publish, none while the run is still running."""
    if status == "paused":
        repos.runs.pause(run_id, reason)
    else:
        repos.runs.end(run_id, status=status, reason=reason, now=now)
    run = require_run(repos, discussion_id, run_id)
    if run.status == "running":
        return ()
    run_state = run_states.get(run.status, "idle")
    repos.threads.set_run_state(discussion_id, run_state, now=now)
    finished_event = record_event(
        events,
        repos,
        discussion_id,
        RUN_FINISHED,
        {
            "run_id": run_id,
            "run_status": run.status,
            "stop_reason": run.stop_reason,
            "rounds_completed": run.rounds_completed,
            "rounds_requested": run.rounds_requested,
            "tokens_used": run.tokens_used,
            "elapsed_ms": run.elapsed_ms,
        },
    )
    thread = repos.threads.get(discussion_id)
    status_event = record_event(
        events,
        repos,
        discussion_id,
        STATUS_CHANGED,
        {
            "run_state": run_state,
            "run_id": run_id,
            "status": thread.status if thread is not None else None,
        },
    )
    log_run_activity(
        repos,
        started_by(run),
        "discussion.run_finished",
        discussion_id,
        {"run_id": run_id, "status": run.status, "stop_reason": run.stop_reason},
        now,
        new_id=new_id,
    )
    return finished_event, status_event
