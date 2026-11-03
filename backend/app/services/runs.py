"""Run control for discussion rounds.

A run is the unit a human steers: it carries the requested rounds, the token and time budgets, the
pause/stop flags and the round history. The engine executes exactly one round at a time; this
service decides whether another round follows, so pause and stop take effect between steps.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, ClassVar
from uuid import uuid4
from weakref import WeakValueDictionary

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .events import (
    CONSENSUS_PROPOSED,
    ROUND_COMPLETED,
    RUN_FINISHED,
    RUN_STARTED,
    STATUS_CHANGED,
    EventService,
)
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)

ACTIVE_RUN_STATUSES = ("running", "paused")
CLOSED_THREAD_STATUSES = {"approved", "vetoed", "cancelled"}
WORKER_THREADS = 4


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


class RunService:
    """Owns run records, the round loop, budgets and the duplicate guard."""

    RUN_STATES: ClassVar[dict[str, str]] = {"paused": "paused", "stopped": "stopped"}

    def __init__(
        self,
        settings: Any,
        board_service: BoardService,
        engine: Orchestrator,
        events: EventService | None = None,
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.boards = board_service.boards
        self.engine = engine
        self.events = events
        self._executor = ThreadPoolExecutor(
            max_workers=WORKER_THREADS, thread_name_prefix="discussion-run"
        )
        self._lock = Lock()
        self._run_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
        self._run_locks_guard = Lock()

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None  # type: ignore[assignment]
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def recover(self, board_id: str) -> int:
        """Fail runs interrupted by a process stop so their threads become usable again.

        Follows decision 0002: an intermediate state is resolved explicitly at startup instead of
        leaving a thread that refuses new runs and review forever.
        """
        if not self.boards.exists(board_id):
            return 0
        now = utcnow()
        with self.boards.session(board_id) as conn:
            failed = conn.execute(
                text(
                    "UPDATE discussion_runs SET status = 'failed',"
                    " stop_reason = 'process_restart', error = 'process_restart',"
                    " finished_at = :now WHERE status IN ('running','paused')"
                ),
                {"now": now},
            ).rowcount
            conn.execute(
                text(
                    "UPDATE discussion_threads SET run_state = 'idle'"
                    " WHERE run_state IN ('running','paused')"
                    " AND NOT EXISTS (SELECT 1 FROM discussion_runs r"
                    "   WHERE r.discussion_id = discussion_threads.id"
                    "   AND r.status IN ('running','paused'))"
                )
            )
        return int(failed or 0)

    # --- serialization -------------------------------------------------------

    def serialize(
        self, conn: Any, run: dict[str, Any], *, with_rounds: bool = True
    ) -> dict[str, Any]:
        entry = dict(run)
        entry["autonomy"] = bool(entry.get("autonomy"))
        entry["rounds"] = (
            _rows(
                conn,
                "SELECT * FROM discussion_rounds WHERE run_id = :id ORDER BY round_number",
                {"id": run["id"]},
            )
            if with_rounds
            else []
        )
        return entry

    def list(self, board_id: str, discussion_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            return self.recent(conn, discussion_id, limit=limit)

    def get(self, board_id: str, discussion_id: str, run_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            return self.serialize(conn, self._run(conn, discussion_id, run_id))

    def recent(self, conn: Any, discussion_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        runs = _rows(
            conn,
            "SELECT * FROM discussion_runs WHERE discussion_id = :id"
            " ORDER BY created_at DESC LIMIT :limit",
            {"id": discussion_id, "limit": limit},
        )
        return [self.serialize(conn, run) for run in runs]

    def active_run(self, conn: Any, discussion_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            text(
                "SELECT * FROM discussion_runs WHERE discussion_id = :id"
                " AND status IN ('running','paused') ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": discussion_id},
        ).mappings().first()
        return dict(row) if row else None

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _run(conn: Any, discussion_id: str, run_id: str) -> dict[str, Any]:
        row = conn.execute(
            text("SELECT * FROM discussion_runs WHERE id = :id AND discussion_id = :thread"),
            {"id": run_id, "thread": discussion_id},
        ).mappings().first()
        if row is None:
            raise NotFound("Discussion run not found")
        return dict(row)

    def _read_run(self, board_id: str, run_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            row = conn.execute(
                text("SELECT * FROM discussion_runs WHERE id = :id"), {"id": run_id}
            ).mappings().first()
        if row is None:
            raise NotFound("Discussion run not found")
        return dict(row)

    @staticmethod
    def _actor(run: dict[str, Any]) -> ActorContext:
        return ActorContext(
            actor_id=run["started_by_actor_id"],
            actor_type=run["started_by_type"],
            actor_name=run["started_by_name"],
            scopes=frozenset({"discussions:write"}),
        )

    def _record(
        self,
        conn: Any,
        discussion_id: str,
        type: str,
        payload: dict[str, Any],
        actor: ActorContext | None = None,
    ) -> dict[str, Any] | None:
        if self.events is None:
            return None
        return self.events.record(
            conn, discussion_id=discussion_id, type=type, payload=payload, actor=actor
        )

    def _publish(self, board_id: str, *events: dict[str, Any] | None) -> None:
        if self.events is None:
            return
        for event in events:
            if event is not None:
                self.events.publish(board_id, event)

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
    ) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            run = self._run(conn, discussion_id, run_id)
            if run["status"] != "running":
                raise Conflict(
                    "Only a running run can be paused", details={"status": run["status"]}
                )
            now = utcnow()
            conn.execute(
                text(
                    "UPDATE discussion_runs SET status = 'paused', stop_reason = 'paused_by_user'"
                    " WHERE id = :id AND status = 'running'"
                ),
                {"id": run_id},
            )
            conn.execute(
                text(
                    "UPDATE discussion_threads SET run_state = 'paused', updated_at = :now"
                    " WHERE id = :id"
                ),
                {"id": discussion_id, "now": now},
            )
            paused_event = self._record(
                conn, discussion_id, STATUS_CHANGED, {"run_state": "paused", "run_id": run_id}
            )
        self._publish(board_id, paused_event)
        return {**self._summary(board_id, discussion_id, run_id), "pending": True}

    def resume(
        self, actor: ActorContext, board_id: str, discussion_id: str, run_id: str
    ) -> dict[str, Any]:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            run = self._run(conn, discussion_id, run_id)
            if run["status"] != "paused":
                raise Conflict(
                    "Only a paused run can be resumed", details={"status": run["status"]}
                )
            now = utcnow()
            conn.execute(
                text(
                    "UPDATE discussion_runs SET status = 'running', stop_reason = NULL"
                    " WHERE id = :id"
                ),
                {"id": run_id},
            )
            conn.execute(
                text(
                    "UPDATE discussion_threads SET run_state = 'running', updated_at = :now"
                    " WHERE id = :id"
                ),
                {"id": discussion_id, "now": now},
            )
            resumed_event = self._record(
                conn, discussion_id, STATUS_CHANGED, {"run_state": "running", "run_id": run_id}
            )
        self._publish(board_id, resumed_event)
        self._submit(board_id, discussion_id, run_id)
        return {**self._summary(board_id, discussion_id, run_id), "pending": True}

    def stop(
        self, actor: ActorContext, board_id: str, discussion_id: str, run_id: str
    ) -> dict[str, Any]:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            run = self._run(conn, discussion_id, run_id)
            if run["status"] not in ACTIVE_RUN_STATUSES:
                raise Conflict(
                    "Run is already finished", details={"status": run["status"]}
                )
            now = utcnow()
            conn.execute(
                text(
                    "UPDATE discussion_runs SET status = 'stopped', stop_reason = 'human_stop',"
                    " finished_at = :now WHERE id = :id"
                    " AND status IN ('running','paused')"
                ),
                {"id": run_id, "now": now},
            )
            self._touch_thread(conn, discussion_id, now, run_state="stopped")
            stopped_event = self._record(
                conn,
                discussion_id,
                RUN_FINISHED,
                {"run_id": run_id, "run_status": "stopped", "stop_reason": "human_stop"},
                actor,
            )
            status_event = self._record(
                conn, discussion_id, STATUS_CHANGED, {"run_state": "stopped", "run_id": run_id}
            )
            log_activity(
                conn,
                actor,
                action="discussion.run_stopped",
                entity_type="discussion",
                entity_id=discussion_id,
                changes={"run_id": run_id},
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
        now = utcnow()
        run_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            thread = conn.execute(
                text("SELECT * FROM discussion_threads WHERE id = :id"), {"id": discussion_id}
            ).mappings().first()
            if thread is None:
                raise NotFound("Discussion not found")
            thread = dict(thread)
            if thread["status"] in CLOSED_THREAD_STATUSES:
                raise Conflict("Discussion is closed", details={"status": thread["status"]})
            participants = conn.execute(
                text("SELECT COUNT(*) FROM discussion_participants WHERE discussion_id = :id"),
                {"id": discussion_id},
            ).scalar_one()
            if not participants:
                raise ValidationFailure("Discussion has no AI participants")
            active = self.active_run(conn, discussion_id)
            if active is not None:
                raise Conflict(
                    "A run is already active",
                    details={"run_id": active["id"], "status": active["status"]},
                )
            requested = (
                rounds
                if rounds is not None
                else (int(thread["max_rounds"]) if autonomous else 1)
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
            conn.execute(
                text(
                    "INSERT INTO discussion_runs"
                    " (id, discussion_id, status, autonomy, rounds_requested, rounds_completed,"
                    "  token_budget, tokens_used, time_budget_seconds, elapsed_ms, stop_reason,"
                    "  error, started_by_actor_id, started_by_type, started_by_name, created_at,"
                    "  started_at, finished_at)"
                    " VALUES (:id, :discussion_id, 'running', :autonomy, :requested, 0,"
                    "         :token_budget, 0, :time_budget, 0, NULL, NULL, :actor_id,"
                    "         :actor_type, :actor_name, :now, :now, NULL)"
                ),
                {
                    "id": run_id,
                    "discussion_id": discussion_id,
                    "autonomy": int(bool(autonomous)),
                    "requested": requested,
                    "token_budget": token_budget,
                    "time_budget": time_budget_seconds,
                    "actor_id": actor.actor_id,
                    "actor_type": actor.actor_type,
                    "actor_name": actor.actor_name,
                    "now": now,
                },
            )
            self._touch_thread(conn, discussion_id, now, run_state="running")
            started_event = self._record(
                conn,
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
            log_activity(
                conn,
                actor,
                action="discussion.run_started",
                entity_type="discussion",
                entity_id=discussion_id,
                changes={
                    "run_id": run_id,
                    "rounds": requested,
                    "autonomous": bool(autonomous),
                    "token_budget": token_budget,
                    "time_budget_seconds": time_budget_seconds,
                },
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

    def _execute(self, board_id: str, discussion_id: str, run_id: str) -> dict[str, Any]:
        with self._run_lock(run_id):
            return self._run_loop(board_id, discussion_id, run_id)

    def _run_loop(self, board_id: str, discussion_id: str, run_id: str) -> dict[str, Any]:
        failures: list[dict[str, str]] = []
        try:
            while True:
                run = self._read_run(board_id, run_id)
                if run["status"] != "running":
                    break
                if run["rounds_completed"] >= run["rounds_requested"]:
                    self._finish(board_id, discussion_id, run_id, "completed", "rounds_completed")
                    break
                if self._time_exhausted(run):
                    self._finish(
                        board_id, discussion_id, run_id, "budget_exhausted", "time_budget"
                    )
                    break
                round_number = int(run["rounds_completed"]) + 1
                outcome = self.engine.run_round(
                    board_id,
                    discussion_id,
                    run_id=run_id,
                    round_number=round_number,
                    token_budget=run["token_budget"],
                )
                failures.extend(outcome["failures"])
                status, reason = self._classify(run, outcome)
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

    def _time_exhausted(self, run: dict[str, Any]) -> bool:
        budget = run.get("time_budget_seconds")
        if budget is None:
            return False
        return int(run["elapsed_ms"]) > int(budget) * 1000

    def _classify(
        self, run: dict[str, Any], outcome: dict[str, Any]
    ) -> tuple[str, str | None]:
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
        elapsed = int(run["elapsed_ms"]) + int(outcome["elapsed_ms"])
        budget = run.get("time_budget_seconds")
        if budget is not None and elapsed > int(budget) * 1000:
            return "budget_exhausted", "time_budget"
        return "completed", None

    def _record_round(
        self,
        board_id: str,
        discussion_id: str,
        run: dict[str, Any],
        outcome: dict[str, Any],
        status: str,
    ) -> None:
        now = utcnow()
        round_status = status
        with self.boards.session(board_id) as conn:
            conn.execute(
                text(
                    "INSERT INTO discussion_rounds"
                    " (id, discussion_id, run_id, round_number, status, answers, failures, repeats,"
                    "  tokens_used, elapsed_ms, created_at, finished_at)"
                    " VALUES (:id, :discussion_id, :run_id, :round, :status, :answers, :failures,"
                    "         :repeats, :tokens, :elapsed, :now, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "discussion_id": discussion_id,
                    "run_id": run["id"],
                    "round": outcome["round_number"],
                    "status": round_status,
                    "answers": outcome["answers"],
                    "failures": len(outcome["failures"]),
                    "repeats": outcome["repeats"],
                    "tokens": outcome["tokens"],
                    "elapsed": outcome["elapsed_ms"],
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "UPDATE discussion_runs SET rounds_completed = :round,"
                    " elapsed_ms = elapsed_ms + :elapsed WHERE id = :id"
                ),
                {
                    "round": outcome["round_number"],
                    "elapsed": outcome["elapsed_ms"],
                    "id": run["id"],
                },
            )
            conn.execute(
                text(
                    "UPDATE discussion_threads SET round_count = round_count + 1, status = :status,"
                    " tokens_used = tokens_used + :tokens, elapsed_ms = elapsed_ms + :elapsed,"
                    " updated_at = :now, last_activity_at = :now WHERE id = :id"
                ),
                {
                    "status": "consensus_proposed" if outcome["unanimous"] else "discussing",
                    "tokens": outcome["tokens"],
                    "elapsed": outcome["elapsed_ms"],
                    "now": now,
                    "id": discussion_id,
                },
            )
            if outcome["unanimous"]:
                conn.execute(
                    text(
                        "INSERT INTO discussion_outcomes"
                        " (id, discussion_id, summary, payload_json, created_at)"
                        " VALUES (:id, :discussion_id, :summary, '{}', :now)"
                    ),
                    {
                        "id": str(uuid4()),
                        "discussion_id": discussion_id,
                        "summary": "All participating agents agreed.",
                        "now": now,
                    },
                )
            thread_status = "consensus_proposed" if outcome["unanimous"] else "discussing"
            round_event = self._record(
                conn,
                discussion_id,
                ROUND_COMPLETED,
                {
                    "run_id": run["id"],
                    "round_number": outcome["round_number"],
                    "status": round_status,
                    "answers": outcome["answers"],
                    "repeats": outcome["repeats"],
                    "failures": len(outcome["failures"]),
                    "tokens_used": outcome["tokens"],
                    "elapsed_ms": outcome["elapsed_ms"],
                },
            )
            status_event = self._record(
                conn,
                discussion_id,
                STATUS_CHANGED,
                {
                    "status": thread_status,
                    "run_state": "running",
                    "run_id": run["id"],
                    "round_number": outcome["round_number"],
                },
            )
            consensus_event = self._record(
                conn,
                discussion_id,
                CONSENSUS_PROPOSED,
                {"run_id": run["id"], "round_number": outcome["round_number"]},
            ) if outcome["unanimous"] else None
            log_activity(
                conn,
                self._actor(run),
                action="discussion.round_completed",
                entity_type="discussion",
                entity_id=discussion_id,
                changes={
                    "run_id": run["id"],
                    "round": outcome["round_number"],
                    "answers": outcome["answers"],
                    "repeats": outcome["repeats"],
                    "failures": len(outcome["failures"]),
                    "status": round_status,
                },
            )
        self._publish(board_id, round_event, status_event, consensus_event)

    def _finish(
        self,
        board_id: str,
        discussion_id: str,
        run_id: str,
        status: str,
        reason: str | None,
    ) -> None:
        now = utcnow()
        with self.boards.session(board_id) as conn:
            if status == "paused":
                conn.execute(
                    text(
                        "UPDATE discussion_runs SET status = 'paused', stop_reason = :reason"
                        " WHERE id = :id AND status = 'running'"
                    ),
                    {"reason": reason, "id": run_id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE discussion_runs SET status = :status, stop_reason = :reason,"
                        " finished_at = :now WHERE id = :id AND status = 'running'"
                    ),
                    {"status": status, "reason": reason, "now": now, "id": run_id},
                )
            run = self._run(conn, discussion_id, run_id)
            if run["status"] == "running":
                return
            run_state = self.RUN_STATES.get(str(run["status"]), "idle")
            self._touch_thread(conn, discussion_id, now, run_state=run_state)
            finished_event = self._record(
                conn,
                discussion_id,
                RUN_FINISHED,
                {
                    "run_id": run_id,
                    "run_status": run["status"],
                    "stop_reason": run["stop_reason"],
                    "rounds_completed": run["rounds_completed"],
                    "rounds_requested": run["rounds_requested"],
                    "tokens_used": run["tokens_used"],
                    "elapsed_ms": run["elapsed_ms"],
                },
            )
            status_event = self._record(
                conn,
                discussion_id,
                STATUS_CHANGED,
                {
                    "run_state": run_state,
                    "run_id": run_id,
                    "status": conn.execute(
                        text("SELECT status FROM discussion_threads WHERE id = :id"),
                        {"id": discussion_id},
                    ).scalar_one_or_none(),
                },
            )
            log_activity(
                conn,
                self._actor(run),
                action="discussion.run_finished",
                entity_type="discussion",
                entity_id=discussion_id,
                changes={
                    "run_id": run_id,
                    "status": run["status"],
                    "stop_reason": run["stop_reason"],
                },
            )
        self._publish(board_id, finished_event, status_event)

    def _fail(self, board_id: str, discussion_id: str, run_id: str, error: str) -> None:
        now = utcnow()
        with self.boards.session(board_id) as conn:
            conn.execute(
                text(
                    "UPDATE discussion_runs SET status = 'failed', stop_reason = 'error',"
                    " error = :error, finished_at = :now WHERE id = :id"
                    " AND status IN ('running','paused')"
                ),
                {"error": error[:2000], "now": now, "id": run_id},
            )
            self._touch_thread(conn, discussion_id, now, run_state="idle")
            failed_event = self._record(
                conn,
                discussion_id,
                RUN_FINISHED,
                {"run_id": run_id, "run_status": "failed", "stop_reason": "error", "error": error},
            )
        self._publish(board_id, failed_event)

    @staticmethod
    def _touch_thread(conn: Any, discussion_id: str, now: str, *, run_state: str) -> None:
        conn.execute(
            text(
                "UPDATE discussion_threads SET run_state = :state, updated_at = :now"
                " WHERE id = :id"
            ),
            {"state": run_state, "now": now, "id": discussion_id},
        )

    # --- summaries -----------------------------------------------------------

    def _summary(self, board_id: str, discussion_id: str, run_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            thread = conn.execute(
                text("SELECT * FROM discussion_threads WHERE id = :id"), {"id": discussion_id}
            ).mappings().first()
            run = self._run(conn, discussion_id, run_id)
            last_round = conn.execute(
                text(
                    "SELECT answers, status FROM discussion_rounds WHERE run_id = :id"
                    " ORDER BY round_number DESC LIMIT 1"
                ),
                {"id": run_id},
            ).first()
            votes = _rows(
                conn,
                "SELECT participant_id, position FROM discussion_votes WHERE discussion_id = :id"
                " ORDER BY rowid DESC",
                {"id": discussion_id},
            )
            latest: dict[str, dict[str, Any]] = {}
            for vote in votes:
                latest.setdefault(vote["participant_id"], vote)
            summary = self.serialize(conn, run)
        return {
            "discussion_id": discussion_id,
            "run_id": run_id,
            "thread_status": thread["status"] if thread else None,
            "status": thread["status"] if thread else None,
            "run_state": thread["run_state"] if thread else "idle",
            "run_status": run["status"],
            "rounds_requested": run["rounds_requested"],
            "rounds_completed": run["rounds_completed"],
            "round_number": run["rounds_completed"],
            "tokens_used": run["tokens_used"],
            "elapsed_ms": run["elapsed_ms"],
            "stop_reason": run["stop_reason"],
            "answers": int(last_round[0]) if last_round else 0,
            "round_status": last_round[1] if last_round else None,
            "votes": list(latest.values()),
            "failures": [],
            "pending": run["status"] == "running",
            "run": summary,
        }
