"""Agent mentions in ticket comments.

A comment that mentions an enabled agent queues one job per agent and returns immediately. The job
row is the status channel (queued → running → completed/failed) and the answer is written back as a
normal agent-authored comment, so the ticket thread stays one chronological conversation. Work runs
on an in-process executor: no broker is introduced for this.

Retry is safe because ``uq_comment_mentions_once`` allows one job per (comment, agent) and the
answer insert is guarded by the job's ``response_comment_id``.

The prompt a mentioned agent receives is built in ``mentions_prompt``.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Lock
from typing import Protocol, TypeGuard
from uuid import uuid4
from weakref import WeakValueDictionary

from ..core.context import ActorContext
from ..core.dates import utcnow
from ..core.errors import Conflict, NotFound
from ..db.generated.board import CommentMentionJobsRow, CommentsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.board_files import AttachmentFiles
from ..repositories.registry import RegistryUnitOfWork
from . import runtime
from .activity import activity_entry
from .agents import RoleSnapshot
from .events import AGENT_COMPLETED, AGENT_FAILED, AGENT_STARTED, Event, EventService
from .mentions_prompt import mention_messages
from .orchestrator import AgentCall, usage_tokens

logger = logging.getLogger("tralala.mentions")

WORKER_THREADS = 2
MAX_MENTIONS_PER_COMMENT = 5

MentionJobEntry = dict[str, object]
"""A job as the API answers it: its columns without the snapshot, the role it ran with, and
whether a person may retry it."""


class BoardChecks(Protocol):
    def require_row(self, board_id: str) -> object: ...

    def ensure_active(self, board_id: str) -> object: ...


class MentionAgents(Protocol):
    def list(self, *, enabled: bool | None = None) -> Sequence[Mapping[str, object]]: ...

    def role_snapshot(self, agent_id: str) -> RoleSnapshot: ...


def extract_mentions(content: str, agents: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return the mentioned agents in order of appearance, without duplicates.

    ``@[Agent Name]`` is the unambiguous form the UI inserts; bare ``@Name`` also works when it
    matches an enabled agent name exactly (longest name wins). An ``@`` inside a word, as in an
    e-mail address, is not a mention.
    """
    by_name = {str(agent["name"]).casefold(): agent for agent in agents}
    ordered = sorted(agents, key=lambda agent: len(str(agent["name"])), reverse=True)
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    index = 0
    while True:
        index = content.find("@", index)
        if index < 0:
            break
        before = content[index - 1] if index else ""
        if before and (before.isalnum() or before in "._-"):
            index += 1
            continue
        rest = content[index + 1 :]
        resolved = None
        if rest.startswith("["):
            end = rest.find("]")
            if end > 0:
                resolved = by_name.get(rest[1:end].strip().casefold())
        if resolved is None:
            for agent in ordered:
                name = str(agent["name"])
                if rest[: len(name)].casefold() != name.casefold():
                    continue
                following = rest[len(name) : len(name) + 1]
                if following and (following.isalnum() or following in "_-."):
                    continue
                resolved = agent
                break
        if resolved is not None and resolved["id"] not in seen:
            seen.add(resolved["id"])
            found.append(resolved)
        index += 1
    return found


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def role_snapshot(job: CommentMentionJobsRow) -> dict[str, object]:
    """The role the job was queued with; an unreadable snapshot reads as none."""
    try:
        snapshot: object = json.loads(job.role_snapshot_json or "{}")
    except ValueError:
        return {}
    return snapshot if _is_object(snapshot) else {}


def serialize_job(job: CommentMentionJobsRow) -> MentionJobEntry:
    entry: MentionJobEntry = dict(asdict(job))
    entry.pop("role_snapshot_json", None)
    snapshot = role_snapshot(job)
    entry["role_template_id"] = snapshot.get("role_template_id")
    entry["role_template_name"] = snapshot.get("role_template_name")
    entry["role_source"] = snapshot.get("role_source")
    entry["system_prompt_sha256"] = snapshot.get("system_prompt_sha256")
    entry["can_retry"] = job.status == "failed" and not job.response_comment_id
    return entry


def agent_actor(agent_id: str, agent_name: str) -> ActorContext:
    return ActorContext(
        actor_id=agent_id,
        actor_type="agent",
        actor_name=agent_name,
        scopes=frozenset({"comments:write"}),
    )


def _new_id() -> str:
    return str(uuid4())


class MentionService:
    """Queues and executes agent replies for mentions in ticket comments."""

    def __init__(
        self,
        settings: object,
        board_service: BoardChecks,
        agents: MentionAgents,
        store: BoardUnitOfWork,
        registry: RegistryUnitOfWork,
        files: AttachmentFiles,
        events: EventService | None = None,
        *,
        call_agent: AgentCall = runtime.call_agent,
        clock: Callable[[], str] = utcnow,
        new_id: Callable[[], str] = _new_id,
        monotonic: Callable[[], float] = time.monotonic,
        background: bool = True,
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.agents = agents
        self.store = store
        self.registry = registry
        self.files = files
        self.events = events
        self._call_agent = call_agent
        self._clock = clock
        self._new_id = new_id
        self._monotonic = monotonic
        # A unit test runs the work inline; the application hands it to a small pool.
        self._executor: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=WORKER_THREADS, thread_name_prefix="comment-mention")
            if background
            else None
        )
        self._background = background
        self._executor_lock = Lock()
        self._job_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
        self._job_locks_guard = Lock()

    def shutdown(self) -> None:
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def recover(self, board_id: str) -> int:
        """Resolve jobs interrupted by a process stop: fail the running ones, resume queued ones."""
        if not self.store.exists(board_id):
            return 0
        now = self._clock()
        with self.store.writer(board_id) as repos:
            failed = repos.mention_jobs.fail_running(now=now)
            queued = repos.mention_jobs.queued_ids()
        for job_id in queued:
            self._submit(board_id, job_id)
        return failed + len(queued)

    # --- reads ---------------------------------------------------------------

    def list(self, board_id: str, card_id: str) -> list[MentionJobEntry]:
        self.board_service.require_row(board_id)
        with self.store.reader(board_id) as repos:
            if repos.cards.get(card_id) is None:
                raise NotFound("Card not found")
            jobs = repos.mention_jobs.for_card(card_id)
        return [serialize_job(job) for job in jobs]

    def _read(self, board_id: str, card_id: str, job_id: str) -> CommentMentionJobsRow:
        with self.store.reader(board_id) as repos:
            job = repos.mention_jobs.get(job_id)
        if job is None or job.card_id != card_id:
            raise NotFound("Mention job not found")
        return job

    # --- queueing ------------------------------------------------------------

    def queue(
        self,
        actor: ActorContext,
        board_id: str,
        card_id: str,
        comment_id: str,
        content: str,
    ) -> list[str]:
        """Create one job per mentioned enabled agent; returns the ids of new jobs."""
        candidates = [
            {"id": str(row["id"]), "name": str(row["name"])}
            for row in self.agents.list(enabled=True)
        ]
        mentioned = extract_mentions(content, candidates)[:MAX_MENTIONS_PER_COMMENT]
        if not mentioned:
            return []
        created: list[str] = []
        now = self._clock()
        with self.store.writer(board_id) as repos:
            comment = repos.comments.get(comment_id)
            if comment is None or comment.card_id != card_id:
                return []
            for agent in mentioned:
                try:
                    snapshot = self.agents.role_snapshot(agent["id"])
                except Exception:  # noqa: BLE001 - a broken agent must not break the comment
                    logger.warning(
                        "Skipping mention of agent %s without a usable role", agent["id"]
                    )
                    continue
                job_id = self._new_id()
                added = repos.mention_jobs.add_once(
                    CommentMentionJobsRow(
                        id=job_id,
                        card_id=card_id,
                        comment_id=comment_id,
                        agent_id=agent["id"],
                        agent_name=agent["name"],
                        status="queued",
                        attempts=0,
                        error=None,
                        response_comment_id=None,
                        role_snapshot_json=json.dumps(snapshot),
                        tokens_used=0,
                        requested_by_actor_id=actor.actor_id,
                        requested_by_type=actor.actor_type,
                        requested_by_name=actor.actor_name,
                        created_at=now,
                        started_at=None,
                        finished_at=None,
                    )
                )
                if added:
                    created.append(job_id)
            if created:
                self._log(
                    repos,
                    actor,
                    "comment.agent_mentioned",
                    "card",
                    card_id,
                    {"agents": [agent["id"] for agent in mentioned], "jobs": created},
                    now,
                )
        for job_id in created:
            self._submit(board_id, job_id)
        return created

    def retry(
        self, actor: ActorContext, board_id: str, card_id: str, job_id: str
    ) -> MentionJobEntry:
        actor.require("comments:write")
        self.board_service.ensure_active(board_id)
        now = self._clock()
        with self.store.writer(board_id) as repos:
            job = repos.mention_jobs.get(job_id)
            if job is None or job.card_id != card_id:
                raise NotFound("Mention job not found")
            if job.response_comment_id:
                raise Conflict(
                    "This mention already has an answer",
                    details={"response_comment_id": job.response_comment_id},
                )
            if job.status in ("queued", "running"):
                raise Conflict("Mention job is already active", details={"status": job.status})
            repos.mention_jobs.requeue(job_id)
            self._log(
                repos,
                actor,
                "comment.mention_retried",
                "card",
                card_id,
                {"job_id": job_id, "agent_id": job.agent_id},
                now,
            )
        self._submit(board_id, job_id)
        return serialize_job(self._read(board_id, card_id, job_id))

    # --- execution -----------------------------------------------------------

    def _submit(self, board_id: str, job_id: str) -> None:
        if not self._background:
            self._worker(board_id, job_id)
            return
        with self._executor_lock:
            executor = self._executor
        if executor is None:
            return
        executor.submit(self._worker, board_id, job_id)

    def _worker(self, board_id: str, job_id: str) -> None:
        try:
            self._execute(board_id, job_id)
        except Exception as exc:  # noqa: BLE001 - a crashed worker must never take the process down
            logger.error("Mention job %s crashed (%s)", job_id, type(exc).__name__)
            self._fail(board_id, job_id, "worker_crashed")

    def _job_lock(self, job_id: str) -> Lock:
        with self._job_locks_guard:
            lock = self._job_locks.get(job_id)
            if lock is None:
                lock = Lock()
                self._job_locks[job_id] = lock
            return lock

    def _execute(self, board_id: str, job_id: str) -> None:
        with self._job_lock(job_id):
            job = self._claim(board_id, job_id)
            if job is None:
                return
            with self.registry.reader() as registry:
                agent = registry.agents.get(job.agent_id)
            if agent is None or not agent.enabled:
                self._fail(board_id, job_id, "agent_missing")
                return
            started = self._monotonic()
            with self.store.reader(board_id) as repos:
                messages = self._messages(repos, job, board_id)
            if messages is None:
                self._fail(board_id, job_id, "comment_deleted")
                return
            result = self._call_agent(
                self.settings,
                asdict(agent),
                system_prompt=str(role_snapshot(job).get("system_prompt") or ""),
                messages=messages,
            )
            duration_ms = int((self._monotonic() - started) * 1000)
            if not result.get("ok"):
                self._fail(board_id, job_id, str(result.get("error")), duration_ms=duration_ms)
                return
            answer = str(result.get("text")).strip()
            self._complete(board_id, job, answer, usage_tokens(result), duration_ms)

    def _claim(self, board_id: str, job_id: str) -> CommentMentionJobsRow | None:
        now = self._clock()
        with self.store.writer(board_id) as repos:
            job = repos.mention_jobs.get(job_id)
            if job is None or job.status != "queued":
                return None
            repos.mention_jobs.start(job_id, now=now)
            event = self._record(
                repos,
                job.card_id,
                AGENT_STARTED,
                {
                    "job_id": job_id,
                    "comment_id": job.comment_id,
                    "agent_id": job.agent_id,
                    "agent_name": job.agent_name,
                },
                actor=agent_actor(job.agent_id, job.agent_name),
            )
        self._publish(board_id, event)
        return job

    def _complete(
        self,
        board_id: str,
        job: CommentMentionJobsRow,
        answer: str,
        tokens: int,
        duration_ms: int,
    ) -> None:
        comment_id = self._new_id()
        now = self._clock()
        speaker = agent_actor(job.agent_id, job.agent_name)
        with self.store.writer(board_id) as repos:
            if not repos.mention_jobs.complete(job.id, tokens=tokens, now=now):
                return
            repos.comments.add(
                CommentsRow(
                    id=comment_id,
                    card_id=job.card_id,
                    actor_id=job.agent_id,
                    content=answer,
                    created_at=now,
                    updated_at=now,
                )
            )
            repos.mention_jobs.set_response(job.id, comment_id)
            self._log(
                repos,
                speaker,
                "comment.agent_replied",
                "comment",
                comment_id,
                {"card_id": job.card_id, "job_id": job.id},
                now,
            )
            event = self._record(
                repos,
                job.card_id,
                AGENT_COMPLETED,
                {
                    "job_id": job.id,
                    "comment_id": job.comment_id,
                    "agent_id": job.agent_id,
                    "agent_name": job.agent_name,
                    "response_comment_id": comment_id,
                    "tokens_used": tokens,
                    "duration_ms": duration_ms,
                },
                actor=speaker,
            )
        self._publish(board_id, event)

    def _fail(self, board_id: str, job_id: str, error: str, *, duration_ms: int = 0) -> None:
        now = self._clock()
        with self.store.writer(board_id) as repos:
            job = repos.mention_jobs.get(job_id)
            if job is None:
                return
            if not repos.mention_jobs.fail(job_id, error=error, now=now):
                return
            speaker = agent_actor(job.agent_id, job.agent_name)
            self._log(
                repos,
                speaker,
                "comment.agent_failed",
                "card",
                job.card_id,
                {"job_id": job_id, "agent_id": job.agent_id, "error": error},
                now,
            )
            event = self._record(
                repos,
                job.card_id,
                AGENT_FAILED,
                {
                    "job_id": job_id,
                    "comment_id": job.comment_id,
                    "agent_id": job.agent_id,
                    "agent_name": job.agent_name,
                    "error": error,
                    "duration_ms": duration_ms,
                },
                actor=speaker,
            )
        self._publish(board_id, event)

    # --- context -------------------------------------------------------------

    def _messages(
        self, repos: BoardRepositories, job: CommentMentionJobsRow, board_id: str
    ) -> list[dict[str, str]] | None:
        return mention_messages(repos, job, board_id, registry=self.registry, files=self.files)

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: Mapping[str, object],
        now: str,
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=now,
            )
        )

    # --- events --------------------------------------------------------------

    def _record(
        self,
        repos: BoardRepositories,
        card_id: str,
        type: str,
        payload: Mapping[str, object],
        *,
        actor: ActorContext | None = None,
    ) -> Event | None:
        if self.events is None:
            return None
        return self.events.record_card(
            repos, card_id=card_id, type=type, payload=payload, actor=actor
        )

    def _publish(self, board_id: str, event: Event | None) -> None:
        if event is not None and self.events is not None:
            self.events.publish(board_id, event)


__all__ = ["MentionAgents", "MentionService", "extract_mentions", "serialize_job"]
