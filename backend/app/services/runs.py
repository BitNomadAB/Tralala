"""Run control for discussion rounds.

A run is the unit a human steers: it carries the requested rounds, the token and time budgets, the
pause/stop flags and the round history. The engine executes exactly one round at a time; this
service decides whether another round follows, so pause and stop take effect between steps.

A run's JSON lives in ``runs_views`` and the round and finish writes in ``runs_rounds``; this module
keeps the service, its executor and locks, and re-exports what callers import from it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import ClassVar, Protocol
from uuid import uuid4
from weakref import WeakValueDictionary

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..db.generated.board import DiscussionRunsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from .events import RUN_FINISHED, RUN_STARTED, STATUS_CHANGED, Event, EventService
from .orchestrator import Failure, RoundOutcome
from .runs_rounds import (
    classify,
    finish_run,
    log_run_activity,
    record_event,
    record_round,
    time_exhausted,
)
from .runs_views import RunEntry, recent_runs, require_run, serialize_run

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "CLOSED_THREAD_STATUSES",
    "WORKER_THREADS",
    "BoardChecks",
    "RoundEngine",
    "RunEntry",
    "RunService",
    "RunSettings",
    "classify",
    "recent_runs",
    "serialize_run",
    "time_exhausted",
]

logger = logging.getLogger("tralala.runs")

ACTIVE_RUN_STATUSES = ("running", "paused")
CLOSED_THREAD_STATUSES = {"approved", "vetoed", "cancelled"}
WORKER_THREADS = 4


class BoardChecks(Protocol):
    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


class RunSettings(Protocol):
    @property
    def discussion_max_rounds(self) -> int: ...

    @property
    def discussion_token_budget(self) -> int: ...

    @property
    def discussion_time_budget_seconds(self) -> int: ...


class RoundEngine(Protocol):
    def run_round(
        self,
        board_id: str,
        discussion_id: str,
        *,
        run_id: str,
        round_number: int,
        token_budget: int | None,
    ) -> RoundOutcome: ...


def _new_id() -> str:
    return str(uuid4())


class RunService:
    """Owns run records, the round loop, budgets and the duplicate guard."""

    RUN_STATES: ClassVar[dict[str, str]] = {"paused": "paused", "stopped": "stopped"}

    def __init__(
        self,
        settings: RunSettings,
        board_service: BoardChecks,
        engine: RoundEngine,
        store: BoardUnitOfWork,
        events: EventService | None = None,
        *,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.engine = engine
        self.store = store
        self.events = events
        self._clock = clock
        self._new_id = new_id
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=WORKER_THREADS, thread_name_prefix="discussion-run"
        )
        self._lock = Lock()
        self._run_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
        self._run_locks_guard = Lock()

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def recover(self, board_id: str) -> int:
        """Fail runs interrupted by a process stop so their threads become usable again.

        An intermediate state is resolved explicitly at startup instead of leaving a thread that
        refuses new runs and review forever.
        """
        if not self.store.exists(board_id):
            return 0
        now = self._clock()
        with self.store.writer(board_id) as repos:
            failed = repos.runs.fail_interrupted(now=now)
            repos.threads.settle_run_states()
        return failed

    # --- serialization -------------------------------------------------------

    def list(self, board_id: str, discussion_id: str, *, limit: int = 20) -> list[RunEntry]:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return recent_runs(repos, discussion_id, limit=limit)

    def get(self, board_id: str, discussion_id: str, run_id: str) -> RunEntry:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return serialize_run(repos, require_run(repos, discussion_id, run_id))

    # --- helpers -------------------------------------------------------------

    def _read_run(self, board_id: str, run_id: str) -> DiscussionRunsRow:
        with self.store.reader(board_id) as repos:
            run = repos.runs.get(run_id)
        if run is None:
            raise NotFound("Discussion run not found")
        return run

    def _record(
        self,
        repos: BoardRepositories,
        discussion_id: str,
        type: str,
        payload: Mapping[str, object],
        actor: ActorContext | None = None,
    ) -> Event | None:
        return record_event(self.events, repos, discussion_id, type, payload, actor)

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
        discussion_id: str,
        changes: Mapping[str, object],
        now: str,
    ) -> None:
        log_run_activity(repos, actor, action, discussion_id, changes, now, new_id=self._new_id)

    # --- commands ------------------------------------------------------------

    def start(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        *,
        rounds: int | None = None,
        autonomous: bool = False,
        token_budget: int | None = None,
        time_budget_seconds: int | None = None,
        background: bool | None = None,
    ) -> RunEntry:
        """Start a run. A single interactive round runs inline; anything longer runs in the back."""
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        run_id, deferred = self._prepare(
            actor,
            board_id,
            discussion_id,
            rounds=rounds,
            autonomous=autonomous,
            token_budget=token_budget,
            time_budget_seconds=time_budget_seconds,
            background=background,
        )
        if deferred:
            self._submit(board_id, discussion_id, run_id)
            return {**self._summary(board_id, discussion_id, run_id), "pending": True}
        return self._execute(board_id, discussion_id, run_id)

    def pause(
        self, actor: ActorContext, board_id: str, discussion_id: str, run_id: str
    ) -> RunEntry:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            run = require_run(repos, discussion_id, run_id)
            if run.status != "running":
                raise Conflict("Only a running run can be paused", details={"status": run.status})
            now = self._clock()
            repos.runs.pause(run_id, "paused_by_user")
            repos.threads.set_run_state(discussion_id, "paused", now=now)
            paused_event = self._record(
                repos, discussion_id, STATUS_CHANGED, {"run_state": "paused", "run_id": run_id}
            )
        self._publish(board_id, paused_event)
        return {**self._summary(board_id, discussion_id, run_id), "pending": True}

    def resume(
        self, actor: ActorContext, board_id: str, discussion_id: str, run_id: str
    ) -> RunEntry:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            run = require_run(repos, discussion_id, run_id)
            if run.status != "paused":
                raise Conflict("Only a paused run can be resumed", details={"status": run.status})
            now = self._clock()
            repos.runs.resume(run_id)
            repos.threads.set_run_state(discussion_id, "running", now=now)
            resumed_event = self._record(
                repos, discussion_id, STATUS_CHANGED, {"run_state": "running", "run_id": run_id}
            )
        self._publish(board_id, resumed_event)
        self._submit(board_id, discussion_id, run_id)
        return {**self._summary(board_id, discussion_id, run_id), "pending": True}

    def stop(
        self, actor: ActorContext, board_id: str, discussion_id: str, run_id: str
    ) -> RunEntry:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            run = require_run(repos, discussion_id, run_id)
            if run.status not in ACTIVE_RUN_STATUSES:
                raise Conflict("Run is already finished", details={"status": run.status})
            now = self._clock()
            repos.runs.stop(run_id, now=now)
            repos.threads.set_run_state(discussion_id, "stopped", now=now)
            stopped_event = self._record(
                repos,
                discussion_id,
                RUN_FINISHED,
                {"run_id": run_id, "run_status": "stopped", "stop_reason": "human_stop"},
                actor,
            )
            status_event = self._record(
                repos, discussion_id, STATUS_CHANGED, {"run_state": "stopped", "run_id": run_id}
            )
            self._log(
                repos, actor, "discussion.run_stopped", discussion_id, {"run_id": run_id}, now
            )
        self._publish(board_id, stopped_event, status_event)
        return self._summary(board_id, discussion_id, run_id)

    # --- preparation ---------------------------------------------------------

    def _prepare(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        *,
        rounds: int | None,
        autonomous: bool,
        token_budget: int | None,
        time_budget_seconds: int | None,
        background: bool | None,
    ) -> tuple[str, bool]:
        now = self._clock()
        run_id = self._new_id()
        with self.store.writer(board_id) as repos:
            thread = repos.threads.get(discussion_id)
            if thread is None:
                raise NotFound("Discussion not found")
            if thread.status in CLOSED_THREAD_STATUSES:
                raise Conflict("Discussion is closed", details={"status": thread.status})
            if not repos.participants.count(discussion_id):
                raise ValidationFailure("Discussion has no AI participants")
            active = repos.runs.active(discussion_id)
            if active is not None:
                raise Conflict(
                    "A run is already active",
                    details={"run_id": active.id, "status": active.status},
                )
            requested = (
                rounds if rounds is not None else (thread.max_rounds if autonomous else 1)
            )
            limit = max(1, int(self.settings.discussion_max_rounds))
            requested = max(1, min(requested, limit))
            # A round cap bounds how many calls a question makes; the budgets bound how big each
            # call may be, which is what actually protects the bill. A configured value of 0 turns
            # the default off, while an explicit 0 from a caller still means "exhaust immediately".
            if token_budget is None and int(self.settings.discussion_token_budget) > 0:
                token_budget = int(self.settings.discussion_token_budget)
            if (
                time_budget_seconds is None
                and int(self.settings.discussion_time_budget_seconds) > 0
            ):
                time_budget_seconds = int(self.settings.discussion_time_budget_seconds)
            deferred = bool(autonomous or requested > 1) if background is None else background
            repos.runs.add(
                DiscussionRunsRow(
                    id=run_id,
                    discussion_id=discussion_id,
                    status="running",
                    autonomy=int(bool(autonomous)),
                    rounds_requested=requested,
                    rounds_completed=0,
                    token_budget=token_budget,
                    tokens_used=0,
                    time_budget_seconds=time_budget_seconds,
                    elapsed_ms=0,
                    stop_reason=None,
                    error=None,
                    started_by_actor_id=actor.actor_id,
                    started_by_type=actor.actor_type,
                    started_by_name=actor.actor_name,
                    created_at=now,
                    started_at=now,
                    finished_at=None,
                )
            )
            repos.threads.set_run_state(discussion_id, "running", now=now)
            started_event = self._record(
                repos,
                discussion_id,
                RUN_STARTED,
                {
                    "run_id": run_id,
                    "rounds_requested": requested,
                    "autonomous": bool(autonomous),
                    "token_budget": token_budget,
                    "time_budget_seconds": time_budget_seconds,
                },
                actor,
            )
            self._log(
                repos,
                actor,
                "discussion.run_started",
                discussion_id,
                {
                    "run_id": run_id,
                    "rounds": requested,
                    "autonomous": bool(autonomous),
                    "token_budget": token_budget,
                    "time_budget_seconds": time_budget_seconds,
                },
                now,
            )
        self._publish(board_id, started_event)
        return run_id, deferred

    # --- execution -----------------------------------------------------------

    def _submit(self, board_id: str, discussion_id: str, run_id: str) -> None:
        with self._lock:
            executor = self._executor
        if executor is None:
            return
        executor.submit(self._worker, board_id, discussion_id, run_id)

    def _worker(self, board_id: str, discussion_id: str, run_id: str) -> None:
        try:
            self._execute(board_id, discussion_id, run_id)
        except Exception as exc:  # noqa: BLE001 - a crashed worker must never take the process down
            logger.error("Discussion run %s crashed (%s)", run_id, type(exc).__name__)
            self._fail(board_id, discussion_id, run_id, "worker_crashed")

    def _run_lock(self, run_id: str) -> Lock:
        """One worker per run: a resumed run must never race the round it just interrupted."""
        with self._run_locks_guard:
            lock = self._run_locks.get(run_id)
            if lock is None:
                lock = Lock()
                self._run_locks[run_id] = lock
            return lock

    def _execute(self, board_id: str, discussion_id: str, run_id: str) -> RunEntry:
        with self._run_lock(run_id):
            return self._run_loop(board_id, discussion_id, run_id)

    def _run_loop(self, board_id: str, discussion_id: str, run_id: str) -> RunEntry:
        failures: list[Failure] = []
        try:
            while True:
                run = self._read_run(board_id, run_id)
                if run.status != "running":
                    break
                if run.rounds_completed >= run.rounds_requested:
                    self._finish(board_id, discussion_id, run_id, "completed", "rounds_completed")
                    break
                if time_exhausted(run):
                    self._finish(
                        board_id, discussion_id, run_id, "budget_exhausted", "time_budget"
                    )
                    break
                outcome = self.engine.run_round(
                    board_id,
                    discussion_id,
                    run_id=run_id,
                    round_number=run.rounds_completed + 1,
                    token_budget=run.token_budget,
                )
                failures.extend(outcome["failures"])
                status, reason = classify(run, outcome)
                self._record_round(board_id, discussion_id, run, outcome, status)
                if status != "completed" or reason == "consensus":
                    self._finish(board_id, discussion_id, run_id, status, reason)
                    break
        except Exception as exc:  # noqa: BLE001 - recorded on the run, surfaced to the caller
            # Exception text can carry SQL values from the board database; keep only the type.
            logger.error("Discussion run %s failed (%s)", run_id, type(exc).__name__)
            self._fail(board_id, discussion_id, run_id, f"round_failed:{type(exc).__name__}")
        summary = self._summary(board_id, discussion_id, run_id)
        summary["failures"] = failures
        return summary

    def _record_round(
        self,
        board_id: str,
        discussion_id: str,
        run: DiscussionRunsRow,
        outcome: RoundOutcome,
        status: str,
    ) -> None:
        now = self._clock()
        with self.store.writer(board_id) as repos:
            published = record_round(
                repos,
                discussion_id,
                run,
                outcome,
                status,
                now=now,
                new_id=self._new_id,
                events=self.events,
            )
        self._publish(board_id, *published)

    def _finish(
        self,
        board_id: str,
        discussion_id: str,
        run_id: str,
        status: str,
        reason: str | None,
    ) -> None:
        now = self._clock()
        with self.store.writer(board_id) as repos:
            published = finish_run(
                repos,
                discussion_id,
                run_id,
                status,
                reason,
                now=now,
                new_id=self._new_id,
                events=self.events,
                run_states=self.RUN_STATES,
            )
        self._publish(board_id, *published)

    def _fail(self, board_id: str, discussion_id: str, run_id: str, error: str) -> None:
        now = self._clock()
        with self.store.writer(board_id) as repos:
            repos.runs.fail(run_id, error=error[:2000], now=now)
            repos.threads.set_run_state(discussion_id, "idle", now=now)
            failed_event = self._record(
                repos,
                discussion_id,
                RUN_FINISHED,
                {"run_id": run_id, "run_status": "failed", "stop_reason": "error", "error": error},
            )
        self._publish(board_id, failed_event)

    # --- summaries -----------------------------------------------------------

    def _summary(self, board_id: str, discussion_id: str, run_id: str) -> RunEntry:
        with self.store.reader(board_id) as repos:
            thread = repos.threads.get(discussion_id)
            run = require_run(repos, discussion_id, run_id)
            last_round = repos.rounds.last_for_run(run_id)
            latest: dict[str, dict[str, object]] = {}
            for vote in repos.votes.newest_first(discussion_id):
                latest.setdefault(
                    vote.participant_id,
                    {"participant_id": vote.participant_id, "position": vote.position},
                )
            summary = serialize_run(repos, run)
        return {
            "discussion_id": discussion_id,
            "run_id": run_id,
            "thread_status": thread.status if thread else None,
            "status": thread.status if thread else None,
            "run_state": thread.run_state if thread else "idle",
            "run_status": run.status,
            "rounds_requested": run.rounds_requested,
            "rounds_completed": run.rounds_completed,
            "round_number": run.rounds_completed,
            "tokens_used": run.tokens_used,
            "elapsed_ms": run.elapsed_ms,
            "stop_reason": run.stop_reason,
            "answers": last_round.answers if last_round else 0,
            "round_status": last_round.status if last_round else None,
            "votes": list(latest.values()),
            "failures": [],
            "pending": run.status == "running",
            "run": summary,
        }

