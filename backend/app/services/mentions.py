"""Agent mentions in ticket comments.

A comment that mentions an enabled agent queues one job per agent and returns immediately. The job
row is the status channel (queued → running → completed/failed) and the answer is written back as a
normal agent-authored comment, so the ticket thread stays one chronological conversation. Work runs
on an in-process executor: no broker is introduced for this.

Retry is safe because ``uq_comment_mentions_once`` allows one job per (comment, agent) and the
answer insert is guarded by the job's ``response_comment_id``.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any
from uuid import uuid4
from weakref import WeakValueDictionary

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound
from ..storage.sqlite import utcnow
from . import runtime
from .activity import log_activity
from .agents import AgentService
from .boards import BoardService
from .events import AGENT_COMPLETED, AGENT_FAILED, AGENT_STARTED, EventService
from .orchestrator import usage_tokens

logger = logging.getLogger(__name__)

WORKER_THREADS = 2
MAX_MENTIONS_PER_COMMENT = 5
RECENT_COMMENTS = 20
CONTEXT_CHARS = 4000


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


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


class MentionService:
    """Queues and executes agent replies for mentions in ticket comments."""

    def __init__(
        self,
        settings: Any,
        board_service: BoardService,
        agents: AgentService,
        events: EventService | None = None,
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.boards = board_service.boards
        self.registry = board_service.registry
        self.agents = agents
        self.events = events
        self._executor = ThreadPoolExecutor(
            max_workers=WORKER_THREADS, thread_name_prefix="comment-mention"
        )
        self._executor_lock = Lock()
        self._job_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()
        self._job_locks_guard = Lock()

    def shutdown(self) -> None:
        with self._executor_lock:
            executor, self._executor = self._executor, None  # type: ignore[assignment]
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def recover(self, board_id: str) -> int:
        """Resolve jobs interrupted by a process stop: fail the running ones, resume queued ones."""
        if not self.boards.exists(board_id):
            return 0
        now = utcnow()
        with self.boards.session(board_id) as conn:
            failed = conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET status = 'failed',"
                    " error = 'process_restart', finished_at = :now"
                    " WHERE status = 'running'"
                ),
                {"now": now},
            ).rowcount
            queued = [
                str(row[0])
                for row in conn.execute(
                    text(
                        "SELECT id FROM comment_mention_jobs WHERE status = 'queued'"
                        " ORDER BY created_at, rowid"
                    )
                )
            ]
        for job_id in queued:
            self._submit(board_id, job_id)
        return int(failed or 0) + len(queued)

    # --- serialization -------------------------------------------------------

    @staticmethod
    def serialize(job: dict[str, Any]) -> dict[str, Any]:
        entry = dict(job)
        snapshot_raw = entry.pop("role_snapshot_json", "{}")
        try:
            snapshot = json.loads(snapshot_raw or "{}")
        except (TypeError, ValueError):
            snapshot = {}
        entry["role_template_id"] = snapshot.get("role_template_id")
        entry["role_template_name"] = snapshot.get("role_template_name")
        entry["role_source"] = snapshot.get("role_source")
        entry["system_prompt_sha256"] = snapshot.get("system_prompt_sha256")
        entry["can_retry"] = entry.get("status") == "failed" and not entry.get(
            "response_comment_id"
        )
        return entry

    def list(self, board_id: str, card_id: str) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            exists = conn.execute(
                text("SELECT 1 FROM cards WHERE id = :id"), {"id": card_id}
            ).first()
            if exists is None:
                raise NotFound("Card not found")
            jobs = _rows(
                conn,
                "SELECT * FROM comment_mention_jobs WHERE card_id = :id"
                " ORDER BY created_at, rowid",
                {"id": card_id},
            )
        return [self.serialize(job) for job in jobs]

    def _read(self, board_id: str, card_id: str, job_id: str) -> dict[str, Any]:
        with self.boards.reader(board_id) as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM comment_mention_jobs WHERE id = :id AND card_id = :card"
                ),
                {"id": job_id, "card": card_id},
            ).mappings().first()
        if row is None:
            raise NotFound("Mention job not found")
        return dict(row)

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
            {"id": row["id"], "name": row["name"]}
            for row in self.agents.list(enabled=True)
        ]
        mentioned = extract_mentions(content, candidates)[:MAX_MENTIONS_PER_COMMENT]
        if not mentioned:
            return []
        created: list[str] = []
        now = utcnow()
        with self.boards.session(board_id) as conn:
            exists = conn.execute(
                text("SELECT 1 FROM comments WHERE id = :id AND card_id = :card"),
                {"id": comment_id, "card": card_id},
            ).first()
            if exists is None:
                return []
            for agent in mentioned:
                try:
                    snapshot = self.agents.role_snapshot(agent["id"])
                except Exception:  # noqa: BLE001 - a broken agent must not break the comment
                    logger.warning(
                        "Skipping mention of agent %s without a usable role", agent["id"]
                    )
                    continue
                job_id = str(uuid4())
                inserted = conn.execute(
                    text(
                        "INSERT OR IGNORE INTO comment_mention_jobs"
                        " (id, card_id, comment_id, agent_id, agent_name, status, attempts,"
                        "  error, response_comment_id, role_snapshot_json, tokens_used,"
                        "  requested_by_actor_id, requested_by_type, requested_by_name,"
                        "  created_at, started_at, finished_at)"
                        " VALUES (:id, :card_id, :comment_id, :agent_id, :agent_name, 'queued',"
                        "         0, NULL, NULL, :snapshot, 0, :actor_id, :actor_type,"
                        "         :actor_name, :now, NULL, NULL)"
                    ),
                    {
                        "id": job_id,
                        "card_id": card_id,
                        "comment_id": comment_id,
                        "agent_id": agent["id"],
                        "agent_name": agent["name"],
                        "snapshot": json.dumps(snapshot),
                        "actor_id": actor.actor_id,
                        "actor_type": actor.actor_type,
                        "actor_name": actor.actor_name,
                        "now": now,
                    },
                )
                if inserted.rowcount:
                    created.append(job_id)
            if created:
                log_activity(
                    conn,
                    actor,
                    action="comment.agent_mentioned",
                    entity_type="card",
                    entity_id=card_id,
                    changes={"agents": [agent["id"] for agent in mentioned], "jobs": created},
                )
        for job_id in created:
            self._submit(board_id, job_id)
        return created

    def retry(
        self, actor: ActorContext, board_id: str, card_id: str, job_id: str
    ) -> dict[str, Any]:
        actor.require("comments:write")
        self.board_service.ensure_active(board_id)
        with self.boards.session(board_id) as conn:
            job = conn.execute(
                text(
                    "SELECT * FROM comment_mention_jobs WHERE id = :id AND card_id = :card"
                ),
                {"id": job_id, "card": card_id},
            ).mappings().first()
            if job is None:
                raise NotFound("Mention job not found")
            if job["response_comment_id"]:
                raise Conflict(
                    "This mention already has an answer",
                    details={"response_comment_id": job["response_comment_id"]},
                )
            if job["status"] in ("queued", "running"):
                raise Conflict("Mention job is already active", details={"status": job["status"]})
            conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET status = 'queued', error = NULL,"
                    " started_at = NULL, finished_at = NULL WHERE id = :id"
                ),
                {"id": job_id},
            )
            log_activity(
                conn,
                actor,
                action="comment.mention_retried",
                entity_type="card",
                entity_id=card_id,
                changes={"job_id": job_id, "agent_id": job["agent_id"]},
            )
        self._submit(board_id, job_id)
        return self.serialize(self._read(board_id, card_id, job_id))

    # --- execution -----------------------------------------------------------

    def _submit(self, board_id: str, job_id: str) -> None:
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
            agent_row = self.registry.read_one(
                "SELECT * FROM agents WHERE id = :id", {"id": job["agent_id"]}
            )
            if agent_row is None or not agent_row.get("enabled"):
                self._fail(board_id, job_id, "agent_missing")
                return
            started = time.monotonic()
            with self.boards.reader(board_id) as conn:
                messages = self._messages(conn, job)
            if messages is None:
                self._fail(board_id, job_id, "comment_deleted")
                return
            snapshot = self._snapshot(job)
            result = runtime.call_agent(
                self.settings,
                agent_row,
                system_prompt=str(snapshot.get("system_prompt") or ""),
                messages=messages,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            if not result["ok"]:
                self._fail(
                    board_id,
                    job_id,
                    str(result["error"]),
                    duration_ms=duration_ms,
                )
                return
            self._complete(
                board_id, job, str(result["text"]).strip(), usage_tokens(result), duration_ms
            )

    def _claim(self, board_id: str, job_id: str) -> dict[str, Any] | None:
        now = utcnow()
        with self.boards.session(board_id) as conn:
            job = conn.execute(
                text("SELECT * FROM comment_mention_jobs WHERE id = :id"), {"id": job_id}
            ).mappings().first()
            if job is None or job["status"] != "queued":
                return None
            row = dict(job)
            conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET status = 'running', attempts = attempts + 1,"
                    " error = NULL, started_at = :now WHERE id = :id"
                ),
                {"id": job_id, "now": now},
            )
            event = self._record(
                conn,
                row["card_id"],
                AGENT_STARTED,
                {
                    "job_id": job_id,
                    "comment_id": row["comment_id"],
                    "agent_id": row["agent_id"],
                    "agent_name": row["agent_name"],
                },
                actor=self._actor(row["agent_id"], row["agent_name"]),
            )
        self._publish(board_id, event)
        return row

    def _complete(
        self, board_id: str, job: dict[str, Any], answer: str, tokens: int, duration_ms: int
    ) -> None:
        comment_id = str(uuid4())
        now = utcnow()
        agent_actor = self._actor(job["agent_id"], job["agent_name"])
        with self.boards.session(board_id) as conn:
            updated = conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET status = 'completed',"
                    " tokens_used = :tokens, error = NULL, finished_at = :now"
                    " WHERE id = :id AND status = 'running' AND response_comment_id IS NULL"
                ),
                {"id": job["id"], "tokens": tokens, "now": now},
            ).rowcount
            if updated != 1:
                return
            conn.execute(
                text(
                    "INSERT INTO comments (id, card_id, actor_id, content, created_at, updated_at)"
                    " VALUES (:id, :card_id, :actor_id, :content, :now, :now)"
                ),
                {
                    "id": comment_id,
                    "card_id": job["card_id"],
                    "actor_id": job["agent_id"],
                    "content": answer,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET response_comment_id = :comment_id"
                    " WHERE id = :id"
                ),
                {"id": job["id"], "comment_id": comment_id},
            )
            log_activity(
                conn,
                agent_actor,
                action="comment.agent_replied",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": job["card_id"], "job_id": job["id"]},
            )
            event = self._record(
                conn,
                job["card_id"],
                AGENT_COMPLETED,
                {
                    "job_id": job["id"],
                    "comment_id": job["comment_id"],
                    "agent_id": job["agent_id"],
                    "agent_name": job["agent_name"],
                    "response_comment_id": comment_id,
                    "tokens_used": tokens,
                    "duration_ms": duration_ms,
                },
                actor=agent_actor,
            )
        self._publish(board_id, event)

    def _fail(
        self,
        board_id: str,
        job_id: str,
        error: str,
        *,
        duration_ms: int = 0,
    ) -> None:
        now = utcnow()
        with self.boards.session(board_id) as conn:
            job = conn.execute(
                text("SELECT * FROM comment_mention_jobs WHERE id = :id"), {"id": job_id}
            ).mappings().first()
            if job is None:
                return
            row = dict(job)
            updated = conn.execute(
                text(
                    "UPDATE comment_mention_jobs SET status = 'failed', error = :error,"
                    " finished_at = :now WHERE id = :id AND status = 'running'"
                ),
                {"id": job_id, "error": error, "now": now},
            ).rowcount
            if updated != 1:
                return
            log_activity(
                conn,
                self._actor(row["agent_id"], row["agent_name"]),
                action="comment.agent_failed",
                entity_type="card",
                entity_id=row["card_id"],
                changes={"job_id": job_id, "agent_id": row["agent_id"], "error": error},
            )
            event = self._record(
                conn,
                row["card_id"],
                AGENT_FAILED,
                {
                    "job_id": job_id,
                    "comment_id": row["comment_id"],
                    "agent_id": row["agent_id"],
                    "agent_name": row["agent_name"],
                    "error": error,
                    "duration_ms": duration_ms,
                },
                actor=self._actor(row["agent_id"], row["agent_name"]),
            )
        self._publish(board_id, event)

    # --- context -------------------------------------------------------------

    def _messages(self, conn: Any, job: dict[str, Any]) -> list[dict[str, str]] | None:
        card = conn.execute(
            text(
                "SELECT c.title, c.description, c.priority, c.due_at, c.completed_at,"
                " l.name AS list"
                " FROM cards c LEFT JOIN lists l ON l.id = c.list_id WHERE c.id = :id"
            ),
            {"id": job["card_id"]},
        ).mappings().first()
        comment = conn.execute(
            text("SELECT content FROM comments WHERE id = :id"), {"id": job["comment_id"]}
        ).first()
        if card is None or comment is None:
            return None
        mentioned_content = str(comment[0])
        labels = [
            row["name"]
            for row in _rows(
                conn,
                "SELECT l.name FROM card_labels cl JOIN labels l ON l.id = cl.label_id"
                " WHERE cl.card_id = :id ORDER BY l.name",
                {"id": job["card_id"]},
            )
        ]
        checklists = _rows(
            conn,
            "SELECT id, title FROM checklists WHERE card_id = :id ORDER BY position, rowid",
            {"id": job["card_id"]},
        )
        items = _rows(
            conn,
            "SELECT checklist_id, text, completed FROM checklist_items WHERE checklist_id IN"
            " (SELECT id FROM checklists WHERE card_id = :id) ORDER BY position, rowid",
            {"id": job["card_id"]},
        )
        history = _rows(
            conn,
            "SELECT c.actor_id, c.content, c.created_at"
            " FROM comments c"
            " WHERE c.card_id = :id AND c.id != :comment"
            " ORDER BY c.created_at DESC, c.rowid DESC LIMIT :limit",
            {"id": job["card_id"], "comment": job["comment_id"], "limit": RECENT_COMMENTS},
        )
        history.reverse()
        attachments = _rows(
            conn,
            "SELECT original_filename, content_type, size_bytes FROM attachments"
            " WHERE card_id = :id AND deleted_at IS NULL ORDER BY created_at",
            {"id": job["card_id"]},
        )
        history = self._decorate_actors(history)

        lines = [
            f"Ticket: {card['title']}",
            f"List: {card['list'] or '(unknown)'}",
            f"Priority: {card['priority']}",
            f"Due: {card['due_at'] or 'none'}",
            f"Status: {'completed' if card['completed_at'] else 'open'}",
            f"Labels: {', '.join(labels) if labels else 'none'}",
            f"Description:\n{(card['description'] or '(empty)')[:CONTEXT_CHARS]}",
        ]
        if checklists:
            lines.append("Checklists:")
            for checklist in checklists:
                entries = [item for item in items if item["checklist_id"] == checklist["id"]]
                rendered = "; ".join(
                    f"[{'x' if item['completed'] else ' '}] {item['text']}" for item in entries
                )
                lines.append(f"- {checklist['title']}: {rendered or '(no items)'}")
        if attachments:
            lines.append("Attachments (metadata only):")
            for attachment in attachments[:20]:
                lines.append(
                    f"- {attachment['original_filename']} ({attachment['content_type']},"
                    f" {attachment['size_bytes']} bytes)"
                )
        transcript = "\n".join(
            f"[{entry.get('actor_name') or 'Unknown'} · {entry.get('actor_type') or 'user'}]"
            f" {str(entry['content'])[:1000]}"
            for entry in history
        )
        sections = ["\n".join(lines)]
        if transcript:
            sections.append(f"Recent comments:\n{transcript}")
        sections.append(
            f"Comment that mentioned you:\n{mentioned_content[:CONTEXT_CHARS]}"
        )
        sections.append(
            "You were mentioned in this ticket. Answer the comment in the ticket thread as your "
            "role: be concise, concrete and actionable. Do not repeat the ticket back. Never "
            "mention other agents."
        )
        return [{"role": "user", "content": "\n\n".join(sections)}]

    def _decorate_actors(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        missing = {
            str(comment["actor_id"])
            for comment in comments
            if comment.get("actor_name") is None and comment.get("actor_id")
        }
        if not missing:
            return comments
        params = {f"a{index}": actor_id for index, actor_id in enumerate(missing)}
        placeholders = ", ".join(f":{key}" for key in params)
        known = {
            row["id"]: row
            for row in self.registry.read(
                f"SELECT id, name, type FROM actors WHERE id IN ({placeholders})", params
            )
        }
        known.update(
            {
                row["id"]: row
                for row in self.registry.read(
                    f"SELECT id, name, 'agent' AS type FROM agents WHERE id IN ({placeholders})",
                    params,
                )
            }
        )
        for comment in comments:
            actor = known.get(str(comment["actor_id"]))
            if actor:
                comment["actor_name"] = actor["name"]
                comment["actor_type"] = actor["type"]
        return comments

    def _snapshot(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            snapshot = json.loads(job.get("role_snapshot_json") or "{}")
        except (TypeError, ValueError):
            snapshot = {}
        return snapshot if isinstance(snapshot, dict) else {}

    @staticmethod
    def _actor(agent_id: str, agent_name: str) -> ActorContext:
        return ActorContext(
            actor_id=agent_id,
            actor_type="agent",
            actor_name=agent_name,
            scopes=frozenset({"comments:write"}),
        )

    # --- events --------------------------------------------------------------

    def _record(
        self,
        conn: Any,
        card_id: str,
        type: str,
        payload: dict[str, Any],
        *,
        actor: ActorContext | None = None,
    ) -> dict[str, Any] | None:
        if self.events is None:
            return None
        return self.events.record_card(
            conn, card_id=card_id, type=type, payload=payload, actor=actor
        )

    def _publish(self, board_id: str, event: dict[str, Any] | None) -> None:
        if event is not None and self.events is not None:
            self.events.publish(board_id, event)


__all__ = ["MentionService", "extract_mentions"]
