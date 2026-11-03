"""``MentionJobRepository`` over SQLAlchemy."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import COMMENT_MENTION_JOBS_COLUMNS, CommentMentionJobsRow

_JOBS = sql.column_list(COMMENT_MENTION_JOBS_COLUMNS)
_FOR_CARD = text(
    f"SELECT {_JOBS} FROM comment_mention_jobs"  # noqa: S608 - from COMMENT_MENTION_JOBS_COLUMNS
    " WHERE card_id = :id ORDER BY created_at, rowid"
)
_GET = text(
    f"SELECT {_JOBS} FROM comment_mention_jobs WHERE id = :id"  # noqa: S608 - generated
)
_ADD_ONCE = text(
    "INSERT OR IGNORE INTO comment_mention_jobs (id, card_id, comment_id, agent_id, agent_name,"
    " status, attempts, error, response_comment_id, role_snapshot_json, tokens_used,"
    " requested_by_actor_id, requested_by_type, requested_by_name, created_at, started_at,"
    " finished_at) VALUES (:id, :card_id, :comment_id, :agent_id, :agent_name, :status,"
    " :attempts, :error, :response_comment_id, :role_snapshot_json, :tokens_used,"
    " :requested_by_actor_id, :requested_by_type, :requested_by_name, :created_at, :started_at,"
    " :finished_at)"
)
_QUEUED = text(
    "SELECT id FROM comment_mention_jobs WHERE status = 'queued' ORDER BY created_at, rowid"
)
_REQUEUE = text(
    "UPDATE comment_mention_jobs SET status = 'queued', error = NULL, started_at = NULL,"
    " finished_at = NULL WHERE id = :id"
)
_START = text(
    "UPDATE comment_mention_jobs SET status = 'running', attempts = attempts + 1, error = NULL,"
    " started_at = :now WHERE id = :id"
)
_COMPLETE = text(
    "UPDATE comment_mention_jobs SET status = 'completed', tokens_used = :tokens, error = NULL,"
    " finished_at = :now WHERE id = :id AND status = 'running' AND response_comment_id IS NULL"
)
_SET_RESPONSE = text(
    "UPDATE comment_mention_jobs SET response_comment_id = :comment_id WHERE id = :id"
)
_FAIL = text(
    "UPDATE comment_mention_jobs SET status = 'failed', error = :error, finished_at = :now"
    " WHERE id = :id AND status = 'running'"
)
_FAIL_RUNNING = text(
    "UPDATE comment_mention_jobs SET status = 'failed', error = 'process_restart',"
    " finished_at = :now WHERE status = 'running'"
)


class SqlMentionJobRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_card(self, card_id: str) -> list[CommentMentionJobsRow]:
        result = self._connection.execute(_FOR_CARD, {"id": card_id}).mappings()
        return [CommentMentionJobsRow.from_mapping(row) for row in result]

    def get(self, job_id: str) -> CommentMentionJobsRow | None:
        row = self._connection.execute(_GET, {"id": job_id}).mappings().first()
        return None if row is None else CommentMentionJobsRow.from_mapping(row)

    def add_once(self, row: CommentMentionJobsRow) -> bool:
        return bool(self._connection.execute(_ADD_ONCE, asdict(row)).rowcount)

    def queued_ids(self) -> list[str]:
        return [values.text(row, "id") for row in self._connection.execute(_QUEUED).mappings()]

    def requeue(self, job_id: str) -> None:
        self._connection.execute(_REQUEUE, {"id": job_id})

    def start(self, job_id: str, *, now: str) -> None:
        self._connection.execute(_START, {"id": job_id, "now": now})

    def complete(self, job_id: str, *, tokens: int, now: str) -> bool:
        parameters = {"id": job_id, "tokens": tokens, "now": now}
        return self._connection.execute(_COMPLETE, parameters).rowcount == 1

    def set_response(self, job_id: str, comment_id: str) -> None:
        self._connection.execute(_SET_RESPONSE, {"id": job_id, "comment_id": comment_id})

    def fail(self, job_id: str, *, error: str, now: str) -> bool:
        parameters = {"id": job_id, "error": error, "now": now}
        return self._connection.execute(_FAIL, parameters).rowcount == 1

    def fail_running(self, *, now: str) -> int:
        return int(self._connection.execute(_FAIL_RUNNING, {"now": now}).rowcount or 0)
