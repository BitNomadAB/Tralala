"""The discussion repositories over SQLAlchemy."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import (
    CARDS_COLUMNS,
    DISCUSSION_MESSAGES_COLUMNS,
    DISCUSSION_OUTCOMES_COLUMNS,
    DISCUSSION_PARTICIPANTS_COLUMNS,
    DISCUSSION_ROUNDS_COLUMNS,
    DISCUSSION_RUNS_COLUMNS,
    DISCUSSION_THREADS_COLUMNS,
    DISCUSSION_VOTES_COLUMNS,
    LOOPS_COLUMNS,
    CardsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
    LoopsRow,
)
from ..discussions import InboxThread, NamedVote

_THREADS = sql.column_list(DISCUSSION_THREADS_COLUMNS)
_MESSAGES = sql.column_list(DISCUSSION_MESSAGES_COLUMNS)
_PARTICIPANTS = sql.column_list(DISCUSSION_PARTICIPANTS_COLUMNS)
_VOTES = sql.column_list(DISCUSSION_VOTES_COLUMNS)
_RUNS = sql.column_list(DISCUSSION_RUNS_COLUMNS)
_ROUNDS = sql.column_list(DISCUSSION_ROUNDS_COLUMNS)
_OUTCOMES = sql.column_list(DISCUSSION_OUTCOMES_COLUMNS)
_CARD = "card__"
_LOOP = "loop__"
_ROUND = "round__"
_OUTCOME = "outcome__"


# --- threads -------------------------------------------------------------------------------------

_THREAD = text(f"SELECT {_THREADS} FROM discussion_threads WHERE id = :id")  # noqa: S608 - generated
_NEWEST_THREADS = text(
    f"SELECT {_THREADS} FROM discussion_threads"  # noqa: S608 - generated
    " WHERE (:status IS NULL OR status = :status) AND (:card_id IS NULL OR card_id = :card_id)"
    " ORDER BY last_activity_at DESC LIMIT :limit"
)
# The inbox reads a board's threads in one statement: each joined row under its own prefix, the
# newest round and the newest outcome picked by the same order their single reads use.
_INBOX = text(
    f"SELECT {sql.column_list(DISCUSSION_THREADS_COLUMNS, 't')},"  # noqa: S608 - generated
    f" {sql.column_list(CARDS_COLUMNS, 'c', _CARD)},"
    f" {sql.column_list(LOOPS_COLUMNS, 'l', _LOOP)},"
    f" {sql.column_list(DISCUSSION_ROUNDS_COLUMNS, 'r', _ROUND)},"
    f" {sql.column_list(DISCUSSION_OUTCOMES_COLUMNS, 'o', _OUTCOME)},"
    " (SELECT COUNT(*) FROM discussion_participants p WHERE p.discussion_id = t.id)"
    " AS participant_count"
    " FROM discussion_threads t"
    " LEFT JOIN cards c ON c.id = t.card_id"
    " LEFT JOIN loops l ON l.id = c.loop_id"
    " LEFT JOIN discussion_rounds r ON r.id = (SELECT lr.id FROM discussion_rounds lr"
    "   WHERE lr.discussion_id = t.id ORDER BY lr.created_at DESC, lr.rowid DESC LIMIT 1)"
    " LEFT JOIN discussion_outcomes o ON o.id = (SELECT lo.id FROM discussion_outcomes lo"
    "   WHERE lo.discussion_id = t.id ORDER BY lo.created_at DESC, lo.rowid DESC LIMIT 1)"
    " WHERE t.status != 'cancelled' ORDER BY t.last_activity_at DESC, t.id LIMIT :limit"
)
_ADD_THREAD = text(
    "INSERT INTO discussion_threads (id, card_id, title, goal, mode, status, "
    "created_by_actor_id, created_by_type, created_by_name, max_rounds, origin_comment_id, "
    "escalation_depth, created_at, updated_at, last_activity_at, round_count, run_state, "
    "tokens_used, elapsed_ms) VALUES (:id, :card_id, :title, :goal, :mode, :status, "
    ":created_by_actor_id, :created_by_type, :created_by_name, :max_rounds, :origin_comment_id,"
    " :escalation_depth, :created_at, :updated_at, :last_activity_at, :round_count, :run_state,"
    " :tokens_used, :elapsed_ms)"
)
_DECIDE = text(
    "UPDATE discussion_threads SET status = :status, updated_at = :now, last_activity_at = :now"
    " WHERE id = :id"
)
_NOTE_MESSAGE = text(
    "UPDATE discussion_threads SET updated_at = :now, last_activity_at = :now,"
    " status = CASE WHEN status = 'open' THEN 'discussing' ELSE status END WHERE id = :id"
)
_SET_RUN_STATE = text(
    "UPDATE discussion_threads SET run_state = :state, updated_at = :now WHERE id = :id"
)
_THREAD_ROUND = text(
    "UPDATE discussion_threads SET round_count = round_count + 1, status = :status,"
    " tokens_used = tokens_used + :tokens, elapsed_ms = elapsed_ms + :elapsed,"
    " updated_at = :now, last_activity_at = :now WHERE id = :id"
)
_SETTLE = text(
    "UPDATE discussion_threads SET run_state = 'idle'"
    " WHERE run_state IN ('running','paused')"
    " AND NOT EXISTS (SELECT 1 FROM discussion_runs r"
    "   WHERE r.discussion_id = discussion_threads.id AND r.status IN ('running','paused'))"
)


def _inbox_thread(row: values.ColumnValues) -> InboxThread:
    """One inbox result row as its rows; a joined row whose ``id`` is NULL was not there."""

    def joined(prefix: str) -> values.ColumnValues | None:
        return None if row[f"{prefix}id"] is None else values.prefixed(row, prefix)

    card, loop, latest, outcome = (joined(p) for p in (_CARD, _LOOP, _ROUND, _OUTCOME))
    return InboxThread(
        thread=DiscussionThreadsRow.from_mapping(row),
        card=None if card is None else CardsRow.from_mapping(card),
        loop=None if loop is None else LoopsRow.from_mapping(loop),
        latest_round=None if latest is None else DiscussionRoundsRow.from_mapping(latest),
        outcome=None if outcome is None else DiscussionOutcomesRow.from_mapping(outcome),
        participant_count=values.integer(row, "participant_count"),
    )


class SqlDiscussionThreadRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, discussion_id: str) -> DiscussionThreadsRow | None:
        row = self._connection.execute(_THREAD, {"id": discussion_id}).mappings().first()
        return None if row is None else DiscussionThreadsRow.from_mapping(row)

    def newest(
        self, *, status: str | None, card_id: str | None, limit: int
    ) -> list[DiscussionThreadsRow]:
        parameters = {"status": status or None, "card_id": card_id or None, "limit": limit}
        result = self._connection.execute(_NEWEST_THREADS, parameters)
        return [DiscussionThreadsRow.from_mapping(row) for row in result.mappings()]

    def inbox(self, *, limit: int) -> list[InboxThread]:
        result = self._connection.execute(_INBOX, {"limit": limit})
        return [_inbox_thread(row) for row in result.mappings()]

    def add(self, row: DiscussionThreadsRow) -> None:
        self._connection.execute(_ADD_THREAD, asdict(row))

    def decide(self, discussion_id: str, status: str, *, now: str) -> None:
        self._connection.execute(_DECIDE, {"status": status, "now": now, "id": discussion_id})

    def note_message(self, discussion_id: str, *, now: str) -> None:
        self._connection.execute(_NOTE_MESSAGE, {"now": now, "id": discussion_id})

    def set_run_state(self, discussion_id: str, run_state: str, *, now: str) -> None:
        self._connection.execute(
            _SET_RUN_STATE, {"state": run_state, "now": now, "id": discussion_id}
        )

    def record_round(
        self, discussion_id: str, *, status: str, tokens: int, elapsed_ms: int, now: str
    ) -> None:
        self._connection.execute(
            _THREAD_ROUND,
            {
                "status": status,
                "tokens": tokens,
                "elapsed": elapsed_ms,
                "now": now,
                "id": discussion_id,
            },
        )

    def settle_run_states(self) -> None:
        self._connection.execute(_SETTLE)


# --- messages ------------------------------------------------------------------------------------

_LIVE = "discussion_id = :id AND deleted_at IS NULL"
_FOR_THREAD = text(
    f"SELECT {_MESSAGES} FROM discussion_messages"  # noqa: S608 - generated
    f" WHERE {_LIVE} ORDER BY created_at"
)
_NEWEST_MESSAGES = text(
    f"SELECT {_MESSAGES} FROM discussion_messages"  # noqa: S608 - generated
    f" WHERE {_LIVE} ORDER BY created_at DESC LIMIT :limit"
)
_COUNT_MESSAGES = text(f"SELECT COUNT(*) FROM discussion_messages WHERE {_LIVE}")  # noqa: S608
_AGENT_ANSWERS = text(
    f"SELECT COUNT(*) FROM discussion_messages WHERE {_LIVE} AND author_type = 'agent'"  # noqa: S608
)
_LAST_DIGEST = text(
    "SELECT content_sha256 FROM discussion_messages"
    " WHERE discussion_id = :id AND author_actor_id = :actor AND deleted_at IS NULL"
    " ORDER BY created_at DESC, rowid DESC LIMIT 1"
)
_BELONGS = text("SELECT 1 FROM discussion_messages WHERE id = :id AND discussion_id = :thread")
_ADD_MESSAGE = text(
    "INSERT INTO discussion_messages (id, discussion_id, parent_message_id, author_actor_id, "
    "author_type, author_name, author_role, content, status, model, created_at, deleted_at, "
    "round_number, content_sha256, answer_json) VALUES (:id, :discussion_id, :parent_message_id, "
    ":author_actor_id, :author_type, :author_name, :author_role, :content, :status, :model, "
    ":created_at, :deleted_at, :round_number, :content_sha256, :answer_json)"
)


class SqlDiscussionMessageRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_thread(self, discussion_id: str) -> list[DiscussionMessagesRow]:
        result = self._connection.execute(_FOR_THREAD, {"id": discussion_id}).mappings()
        return [DiscussionMessagesRow.from_mapping(row) for row in result]

    def newest(self, discussion_id: str, *, limit: int) -> list[DiscussionMessagesRow]:
        parameters = {"id": discussion_id, "limit": limit}
        result = self._connection.execute(_NEWEST_MESSAGES, parameters).mappings()
        return [DiscussionMessagesRow.from_mapping(row) for row in result]

    def count(self, discussion_id: str) -> int:
        return int(self._connection.execute(_COUNT_MESSAGES, {"id": discussion_id}).scalar_one())

    def agent_answers(self, discussion_id: str) -> int:
        return int(self._connection.execute(_AGENT_ANSWERS, {"id": discussion_id}).scalar_one())

    def last_digest(self, discussion_id: str, author_actor_id: str) -> str | None:
        parameters = {"id": discussion_id, "actor": author_actor_id}
        row = self._connection.execute(_LAST_DIGEST, parameters).mappings().first()
        return None if row is None else values.text_or_none(row, "content_sha256")

    def belongs(self, message_id: str, discussion_id: str) -> bool:
        parameters = {"id": message_id, "thread": discussion_id}
        return self._connection.execute(_BELONGS, parameters).first() is not None

    def add(self, row: DiscussionMessagesRow) -> None:
        self._connection.execute(_ADD_MESSAGE, asdict(row))


# --- participants and votes ----------------------------------------------------------------------

_PARTICIPANTS_OF = text(
    f"SELECT {_PARTICIPANTS} FROM discussion_participants"  # noqa: S608 - generated
    " WHERE discussion_id = :id ORDER BY joined_at"
)
_COUNT_PARTICIPANTS = text(
    "SELECT COUNT(*) FROM discussion_participants WHERE discussion_id = :id"
)
_ADD_PARTICIPANT = text(
    "INSERT INTO discussion_participants (id, discussion_id, participant_id, participant_type, "
    "display_name, role_template_id, role_template_name, role_template_updated_at, role_source,"
    " system_prompt, system_prompt_sha256, snapshot_at, joined_at) VALUES (:id, :discussion_id,"
    " :participant_id, :participant_type, :display_name, :role_template_id, "
    ":role_template_name, :role_template_updated_at, :role_source, :system_prompt, "
    ":system_prompt_sha256, :snapshot_at, :joined_at)"
)
_NAMED_VOTES = text(
    "SELECT v.participant_id, p.display_name, v.position, v.justification, v.round_number,"
    " v.created_at FROM discussion_votes v"
    " LEFT JOIN discussion_participants p ON p.participant_id = v.participant_id"
    " WHERE v.discussion_id = :id ORDER BY v.created_at, v.rowid"
)
_LATEST_POSITION = text(
    "SELECT position FROM discussion_votes WHERE discussion_id = :id"
    " AND participant_id = :participant ORDER BY round_number DESC, rowid DESC LIMIT 1"
)
_VOTES_NEWEST_FIRST = text(
    f"SELECT {_VOTES} FROM discussion_votes"  # noqa: S608 - generated
    " WHERE discussion_id = :id ORDER BY rowid DESC"
)
_ADD_VOTE = text(
    "INSERT INTO discussion_votes (id, discussion_id, participant_id, position, justification, "
    "created_at, round_number) VALUES (:id, :discussion_id, :participant_id, :position, "
    ":justification, :created_at, :round_number)"
)


class SqlDiscussionParticipantRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_thread(self, discussion_id: str) -> list[DiscussionParticipantsRow]:
        result = self._connection.execute(_PARTICIPANTS_OF, {"id": discussion_id}).mappings()
        return [DiscussionParticipantsRow.from_mapping(row) for row in result]

    def count(self, discussion_id: str) -> int:
        result = self._connection.execute(_COUNT_PARTICIPANTS, {"id": discussion_id})
        return int(result.scalar_one())

    def add(self, row: DiscussionParticipantsRow) -> None:
        self._connection.execute(_ADD_PARTICIPANT, asdict(row))


class SqlDiscussionVoteRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def with_names(self, discussion_id: str) -> list[NamedVote]:
        result = self._connection.execute(_NAMED_VOTES, {"id": discussion_id}).mappings()
        return [
            {
                "participant_id": values.text(row, "participant_id"),
                "display_name": values.text_or_none(row, "display_name"),
                "position": values.text(row, "position"),
                "justification": values.text(row, "justification"),
                "round_number": values.integer(row, "round_number"),
                "created_at": values.text(row, "created_at"),
            }
            for row in result
        ]

    def latest_position(self, discussion_id: str, participant_id: str) -> str | None:
        parameters = {"id": discussion_id, "participant": participant_id}
        row = self._connection.execute(_LATEST_POSITION, parameters).mappings().first()
        return None if row is None else values.text(row, "position")

    def newest_first(self, discussion_id: str) -> list[DiscussionVotesRow]:
        result = self._connection.execute(_VOTES_NEWEST_FIRST, {"id": discussion_id}).mappings()
        return [DiscussionVotesRow.from_mapping(row) for row in result]

    def add(self, row: DiscussionVotesRow) -> None:
        self._connection.execute(_ADD_VOTE, asdict(row))


# --- runs, rounds, outcomes ----------------------------------------------------------------------

_RUN = text(f"SELECT {_RUNS} FROM discussion_runs WHERE id = :id")  # noqa: S608 - generated
_RECENT_RUNS = text(
    f"SELECT {_RUNS} FROM discussion_runs"  # noqa: S608 - generated
    " WHERE discussion_id = :id ORDER BY created_at DESC LIMIT :limit"
)
_ACTIVE_RUN = text(
    f"SELECT {_RUNS} FROM discussion_runs"  # noqa: S608 - generated
    " WHERE discussion_id = :id AND status IN ('running','paused')"
    " ORDER BY created_at DESC LIMIT 1"
)
_ADD_RUN = text(
    "INSERT INTO discussion_runs (id, discussion_id, status, autonomy, rounds_requested, "
    "rounds_completed, token_budget, tokens_used, time_budget_seconds, elapsed_ms, stop_reason,"
    " error, started_by_actor_id, started_by_type, started_by_name, created_at, started_at, "
    "finished_at) VALUES (:id, :discussion_id, :status, :autonomy, :rounds_requested, "
    ":rounds_completed, :token_budget, :tokens_used, :time_budget_seconds, :elapsed_ms, "
    ":stop_reason, :error, :started_by_actor_id, :started_by_type, :started_by_name, "
    ":created_at, :started_at, :finished_at)"
)
_PAUSE = text(
    "UPDATE discussion_runs SET status = 'paused', stop_reason = :reason"
    " WHERE id = :id AND status = 'running'"
)
_RESUME = text("UPDATE discussion_runs SET status = 'running', stop_reason = NULL WHERE id = :id")
_END = text(
    "UPDATE discussion_runs SET status = :status, stop_reason = :reason, finished_at = :now"
    " WHERE id = :id AND status = 'running'"
)
_STOP = text(
    "UPDATE discussion_runs SET status = 'stopped', stop_reason = 'human_stop',"
    " finished_at = :now WHERE id = :id AND status IN ('running','paused')"
)
_FAIL = text(
    "UPDATE discussion_runs SET status = 'failed', stop_reason = 'error', error = :error,"
    " finished_at = :now WHERE id = :id AND status IN ('running','paused')"
)
_FAIL_INTERRUPTED = text(
    "UPDATE discussion_runs SET status = 'failed', stop_reason = 'process_restart',"
    " error = 'process_restart', finished_at = :now WHERE status IN ('running','paused')"
)
_RUN_ROUND = text(
    "UPDATE discussion_runs SET rounds_completed = :round, elapsed_ms = elapsed_ms + :elapsed"
    " WHERE id = :id"
)
_ADD_TOKENS = text("UPDATE discussion_runs SET tokens_used = tokens_used + :tokens WHERE id = :id")
_ROUNDS_OF = text(
    f"SELECT {_ROUNDS} FROM discussion_rounds"  # noqa: S608 - generated
    " WHERE run_id = :id ORDER BY round_number"
)
_LAST_ROUND = text(
    f"SELECT {_ROUNDS} FROM discussion_rounds"  # noqa: S608 - generated
    " WHERE run_id = :id ORDER BY round_number DESC LIMIT 1"
)
_NEWEST_ROUND = text(
    f"SELECT {_ROUNDS} FROM discussion_rounds"  # noqa: S608 - generated
    " WHERE discussion_id = :id ORDER BY created_at DESC, rowid DESC LIMIT 1"
)
_ADD_ROUND = text(
    "INSERT INTO discussion_rounds (id, discussion_id, run_id, round_number, status, answers, "
    "failures, repeats, tokens_used, elapsed_ms, created_at, finished_at, synthesis_json) VALUES "
    "(:id, :discussion_id, :run_id, :round_number, :status, :answers, :failures, :repeats, "
    ":tokens_used, :elapsed_ms, :created_at, :finished_at, :synthesis_json)"
)
_NEWEST_OUTCOME = text(
    f"SELECT {_OUTCOMES} FROM discussion_outcomes"  # noqa: S608 - generated
    " WHERE discussion_id = :id ORDER BY created_at DESC, rowid DESC LIMIT 1"
)
_ADD_OUTCOME = text(
    "INSERT INTO discussion_outcomes (id, discussion_id, summary, payload_json, created_at)"
    " VALUES (:id, :discussion_id, :summary, :payload_json, :created_at)"
)


class SqlDiscussionRunRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, run_id: str) -> DiscussionRunsRow | None:
        row = self._connection.execute(_RUN, {"id": run_id}).mappings().first()
        return None if row is None else DiscussionRunsRow.from_mapping(row)

    def recent(self, discussion_id: str, *, limit: int) -> list[DiscussionRunsRow]:
        parameters = {"id": discussion_id, "limit": limit}
        result = self._connection.execute(_RECENT_RUNS, parameters).mappings()
        return [DiscussionRunsRow.from_mapping(row) for row in result]

    def active(self, discussion_id: str) -> DiscussionRunsRow | None:
        row = self._connection.execute(_ACTIVE_RUN, {"id": discussion_id}).mappings().first()
        return None if row is None else DiscussionRunsRow.from_mapping(row)

    def add(self, row: DiscussionRunsRow) -> None:
        self._connection.execute(_ADD_RUN, asdict(row))

    def pause(self, run_id: str, reason: str | None) -> None:
        self._connection.execute(_PAUSE, {"reason": reason, "id": run_id})

    def resume(self, run_id: str) -> None:
        self._connection.execute(_RESUME, {"id": run_id})

    def end(self, run_id: str, *, status: str, reason: str | None, now: str) -> None:
        parameters = {"status": status, "reason": reason, "now": now, "id": run_id}
        self._connection.execute(_END, parameters)

    def stop(self, run_id: str, *, now: str) -> None:
        self._connection.execute(_STOP, {"now": now, "id": run_id})

    def fail(self, run_id: str, *, error: str, now: str) -> None:
        self._connection.execute(_FAIL, {"error": error, "now": now, "id": run_id})

    def fail_interrupted(self, *, now: str) -> int:
        return int(self._connection.execute(_FAIL_INTERRUPTED, {"now": now}).rowcount or 0)

    def record_round(self, run_id: str, *, round_number: int, elapsed_ms: int) -> None:
        parameters = {"round": round_number, "elapsed": elapsed_ms, "id": run_id}
        self._connection.execute(_RUN_ROUND, parameters)

    def add_tokens(self, run_id: str, tokens: int) -> None:
        self._connection.execute(_ADD_TOKENS, {"tokens": tokens, "id": run_id})


class SqlDiscussionRoundRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def for_run(self, run_id: str) -> list[DiscussionRoundsRow]:
        result = self._connection.execute(_ROUNDS_OF, {"id": run_id}).mappings()
        return [DiscussionRoundsRow.from_mapping(row) for row in result]

    def last_for_run(self, run_id: str) -> DiscussionRoundsRow | None:
        row = self._connection.execute(_LAST_ROUND, {"id": run_id}).mappings().first()
        return None if row is None else DiscussionRoundsRow.from_mapping(row)

    def newest_for_thread(self, discussion_id: str) -> DiscussionRoundsRow | None:
        row = self._connection.execute(_NEWEST_ROUND, {"id": discussion_id}).mappings().first()
        return None if row is None else DiscussionRoundsRow.from_mapping(row)

    def add(self, row: DiscussionRoundsRow) -> None:
        self._connection.execute(_ADD_ROUND, asdict(row))


class SqlDiscussionOutcomeRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def newest(self, discussion_id: str) -> DiscussionOutcomesRow | None:
        row = self._connection.execute(_NEWEST_OUTCOME, {"id": discussion_id}).mappings().first()
        return None if row is None else DiscussionOutcomesRow.from_mapping(row)

    def add(self, row: DiscussionOutcomesRow) -> None:
        self._connection.execute(_ADD_OUTCOME, asdict(row))
