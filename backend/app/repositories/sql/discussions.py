"""The discussion repositories over SQLAlchemy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from ...core import sql
from ...db import values
from ...db.generated.board import (
    CARDS_COLUMNS,
    DISCUSSION_MESSAGES_COLUMNS,
    DISCUSSION_OUTCOMES_COLUMNS,
    DISCUSSION_PARTICIPANTS_COLUMNS,
    DISCUSSION_READS_COLUMNS,
    DISCUSSION_ROUNDS_COLUMNS,
    DISCUSSION_RUNS_COLUMNS,
    DISCUSSION_THREADS_COLUMNS,
    DISCUSSION_VOTES_COLUMNS,
    LOOPS_COLUMNS,
    CardsRow,
    DiscussionMessagesRow,
    DiscussionOutcomesRow,
    DiscussionParticipantsRow,
    DiscussionReadsRow,
    DiscussionRoundsRow,
    DiscussionRunsRow,
    DiscussionThreadsRow,
    DiscussionVotesRow,
    LoopsRow,
)
from ..discussions import InboxThread, NamedVote, NoticeThread, ThreadState

_THREADS = sql.column_list(DISCUSSION_THREADS_COLUMNS)
_MESSAGES = sql.column_list(DISCUSSION_MESSAGES_COLUMNS)
_PARTICIPANTS = sql.column_list(DISCUSSION_PARTICIPANTS_COLUMNS)
_READS = sql.column_list(DISCUSSION_READS_COLUMNS)
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
    " AND (:board_level IS NULL OR (card_id IS NULL) = :board_level)"
    " AND (:state IS NULL OR (status = 'closed') = (:state = 'closed'))"
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
    "tokens_used, elapsed_ms, closed_at, closed_by_actor_id) VALUES (:id, :card_id, :title, "
    ":goal, :mode, :status, :created_by_actor_id, :created_by_type, :created_by_name, "
    ":max_rounds, :origin_comment_id, :escalation_depth, :created_at, :updated_at, "
    ":last_activity_at, :round_count, :run_state, :tokens_used, :elapsed_ms, :closed_at, "
    ":closed_by_actor_id)"
)
_DECIDE = text(
    "UPDATE discussion_threads SET status = :status, updated_at = :now, last_activity_at = :now"
    " WHERE id = :id"
)
_CLOSE = text(
    "UPDATE discussion_threads SET status = 'closed', closed_at = :now,"
    " closed_by_actor_id = :actor, updated_at = :now, last_activity_at = :now WHERE id = :id"
)
_REOPEN = text(
    "UPDATE discussion_threads SET status = 'discussing', closed_at = NULL,"
    " closed_by_actor_id = NULL, updated_at = :now, last_activity_at = :now WHERE id = :id"
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
        self,
        *,
        status: str | None,
        card_id: str | None,
        limit: int,
        board_level: bool | None = None,
        state: ThreadState | None = None,
    ) -> list[DiscussionThreadsRow]:
        parameters = {
            "status": status or None,
            "card_id": card_id or None,
            "limit": limit,
            "board_level": board_level,
            "state": state,
        }
        result = self._connection.execute(_NEWEST_THREADS, parameters)
        return [DiscussionThreadsRow.from_mapping(row) for row in result.mappings()]

    def inbox(self, *, limit: int) -> list[InboxThread]:
        result = self._connection.execute(_INBOX, {"limit": limit})
        return [_inbox_thread(row) for row in result.mappings()]

    def add(self, row: DiscussionThreadsRow) -> None:
        self._connection.execute(_ADD_THREAD, asdict(row))

    def decide(self, discussion_id: str, status: str, *, now: str) -> None:
        self._connection.execute(_DECIDE, {"status": status, "now": now, "id": discussion_id})

    def close(self, discussion_id: str, *, actor_id: str, now: str) -> None:
        self._connection.execute(_CLOSE, {"now": now, "actor": actor_id, "id": discussion_id})

    def reopen(self, discussion_id: str, *, now: str) -> None:
        self._connection.execute(_REOPEN, {"now": now, "id": discussion_id})

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
    "round_number, content_sha256, answer_json, after_closed, ref_card_id) VALUES (:id, "
    ":discussion_id, :parent_message_id, :author_actor_id, :author_type, :author_name, "
    ":author_role, :content, :status, :model, :created_at, :deleted_at, :round_number, "
    ":content_sha256, :answer_json, :after_closed, :ref_card_id)"
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


# --- read markers --------------------------------------------------------------------------------

_READ = text(
    f"SELECT {_READS} FROM discussion_reads"  # noqa: S608 - generated
    " WHERE discussion_id = :id AND actor_id = :actor"
)
_MARK_READ = text(
    "INSERT INTO discussion_reads (discussion_id, actor_id, last_read_at)"
    " VALUES (:id, :actor, :now)"
    " ON CONFLICT(discussion_id, actor_id) DO UPDATE SET last_read_at = excluded.last_read_at"
)
# A thread is unread for the actor when someone else wrote a message in it, not deleted, after the
# actor's marker, or when the actor has no marker for it at all.
_UNREAD = text(
    "SELECT DISTINCT m.discussion_id FROM discussion_messages m"
    " LEFT JOIN discussion_reads r ON r.discussion_id = m.discussion_id AND r.actor_id = :actor"
    " WHERE m.discussion_id IN :ids AND m.deleted_at IS NULL AND m.author_actor_id != :actor"
    " AND (r.last_read_at IS NULL OR m.created_at > r.last_read_at)"
).bindparams(bindparam("ids", expanding=True))
# What may wait for the actor, in one statement over the board's threads (one row each; who opened
# one has no index, so they are scanned). The candidates are the threads the actor opened or wrote
# in (``ix_discussion_messages_thread``), those with a run the actor started that failed
# (``ix_discussion_runs_status``), and the open questions: threads on the board in a status that
# still takes answers for which the actor holds no marker (``ix_discussion_reads_actor``). Each
# candidate carries its marker (the reads' key), whether the actor is involved, the
# ``after_closed`` of the newest message by someone else after the marker (NULL when there is
# none) and whether a run the actor started failed after the marker; only the rows with a reason
# are kept.
_NOTICES = text(
    "WITH facts AS ("  # noqa: S608 - generated
    f" SELECT {sql.column_list(DISCUSSION_THREADS_COLUMNS, 't')},"
    " r.last_read_at AS marker,"
    " (t.created_by_actor_id = :actor OR EXISTS (SELECT 1 FROM discussion_messages w"
    "   WHERE w.discussion_id = t.id AND w.author_actor_id = :actor)) AS involved,"
    " (SELECT n.after_closed FROM discussion_messages n"
    "   WHERE n.discussion_id = t.id AND n.deleted_at IS NULL AND n.author_actor_id != :actor"
    "   AND (r.last_read_at IS NULL OR n.created_at > r.last_read_at)"
    "   ORDER BY n.created_at DESC, n.rowid DESC LIMIT 1) AS news_after_closed,"
    " EXISTS (SELECT 1 FROM discussion_runs f"
    "   WHERE f.discussion_id = t.id AND f.started_by_actor_id = :actor AND f.status = 'failed'"
    "   AND (r.last_read_at IS NULL OR COALESCE(f.finished_at, f.created_at) > r.last_read_at))"
    " AS run_failed"
    " FROM discussion_threads t"
    " LEFT JOIN discussion_reads r ON r.discussion_id = t.id AND r.actor_id = :actor"
    " WHERE t.created_by_actor_id = :actor"
    " OR EXISTS (SELECT 1 FROM discussion_messages m"
    "   WHERE m.discussion_id = t.id AND m.author_actor_id = :actor)"
    " OR t.id IN (SELECT u.discussion_id FROM discussion_runs u"
    "   WHERE u.status = 'failed' AND u.started_by_actor_id = :actor)"
    " OR (t.card_id IS NULL AND t.status NOT IN ('closed', 'cancelled', 'approved', 'vetoed')"
    "   AND t.id NOT IN (SELECT o.discussion_id FROM discussion_reads o WHERE o.actor_id = :actor))"
    f") SELECT {_THREADS}, marker, involved, news_after_closed, run_failed FROM facts"
    " WHERE (involved AND news_after_closed IS NOT NULL) OR run_failed"
    " OR (card_id IS NULL AND status NOT IN ('closed', 'cancelled', 'approved', 'vetoed')"
    "   AND NOT involved AND marker IS NULL)"
    " ORDER BY last_activity_at DESC, id LIMIT :limit"
)


def _notice_thread(row: values.ColumnValues) -> NoticeThread:
    after_closed = values.integer_or_none(row, "news_after_closed")
    return NoticeThread(
        thread=DiscussionThreadsRow.from_mapping(row),
        involved=values.flag(row, "involved"),
        marked=values.text_or_none(row, "marker") is not None,
        news=after_closed is not None,
        news_after_closed=bool(after_closed),
        run_failed=values.flag(row, "run_failed"),
    )


class SqlDiscussionReadRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, discussion_id: str, actor_id: str) -> DiscussionReadsRow | None:
        parameters = {"id": discussion_id, "actor": actor_id}
        row = self._connection.execute(_READ, parameters).mappings().first()
        return None if row is None else DiscussionReadsRow.from_mapping(row)

    def mark(self, discussion_id: str, actor_id: str, *, now: str) -> None:
        parameters = {"id": discussion_id, "actor": actor_id, "now": now}
        self._connection.execute(_MARK_READ, parameters)

    def unread_ids(self, actor_id: str, discussion_ids: Sequence[str]) -> set[str]:
        if not discussion_ids:
            return set()
        parameters = {"actor": actor_id, "ids": list(discussion_ids)}
        result = self._connection.execute(_UNREAD, parameters).mappings()
        return {values.text(row, "discussion_id") for row in result}

    def notices(self, actor_id: str, *, limit: int) -> list[NoticeThread]:
        result = self._connection.execute(_NOTICES, {"actor": actor_id, "limit": limit})
        return [_notice_thread(row) for row in result.mappings()]


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
