"""Discussion round engine: one bounded round of agent answers with structured positions.

The engine never decides whether another round should follow; ``RunService`` owns the loop, the
budgets and the run record.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.errors import NotFound
from ..storage.sqlite import utcnow
from . import runtime
from .boards import BoardService
from .events import (
    AGENT_COMPLETED,
    AGENT_FAILED,
    AGENT_STARTED,
    MESSAGE_CREATED,
    VOTE_RECORDED,
    EventService,
)


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def content_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def usage_tokens(result: dict[str, Any]) -> int:
    usage = result.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)):
        return int(total)
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
        return int(prompt) + int(completion)
    return 0


class Orchestrator:
    """Runs one bounded round per participant and records explicit positions."""

    def __init__(
        self, settings: Any, board_service: BoardService, events: EventService | None = None
    ) -> None:
        self.settings = settings
        self.board_service = board_service
        self.boards = board_service.boards
        self.events = events

    def _context(self, conn: Any, thread: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
        card = conn.execute(
            text(
                "SELECT c.id, c.title, c.description, c.priority, c.ticket_key,"
                " l.key AS loop_key, l.name AS loop_name"
                " FROM cards c LEFT JOIN loops l ON l.id = c.loop_id WHERE c.id = :id"
            ),
            {"id": thread["card_id"]},
        ).mappings().first()
        history = _rows(
            conn,
            "SELECT author_name, author_type, content FROM discussion_messages"
            " WHERE discussion_id = :id AND deleted_at IS NULL ORDER BY created_at DESC"
            " LIMIT :limit",
            {"id": thread["id"], "limit": limit},
        )
        history.reverse()
        # A card gets its key when a plan is published, so a thread on an unplanned ticket names the
        # id instead. Either way the agent is told which ticket it is looking at.
        ticket = (
            f"Loop: {card['loop_name'] or '(unknown)'} ({card['loop_key'] or 'no key'})\n"
            f"Ticket: {card['title']}\n"
            f"Ticket id: {card['id']} (key: {card['ticket_key'] or 'not keyed yet'})\n"
            f"Priority: {card['priority']}\n"
            f"Description:\n{(card['description'] or '(empty)')[:4000]}"
            if card
            else "Ticket: (missing)"
        )
        transcript = "\n\n".join(
            f"[{entry['author_name']} · {entry['author_type']}] {entry['content'][:1500]}"
            for entry in history
        )
        return [
            {
                "role": "user",
                "content": (
                    f"{ticket}\n\nDiscussion goal: {thread['goal']}\n\n"
                    f"Transcript so far:\n{transcript}\n\n"
                    "Respond with your analysis from your role. End with a single verdict word: "
                    "AGREE, DISAGREE or ABSTAIN."
                ),
            }
        ]

    def _run_state(self, board_id: str, run_id: str) -> tuple[str, int]:
        with self.boards.reader(board_id) as conn:
            row = conn.execute(
                text("SELECT status, tokens_used FROM discussion_runs WHERE id = :id"),
                {"id": run_id},
            ).first()
        if row is None:
            raise NotFound("Discussion run not found")
        return str(row[0]), int(row[1])

    @staticmethod
    def _latest_position(conn: Any, discussion_id: str, participant_id: str) -> str | None:
        row = conn.execute(
            text(
                "SELECT position FROM discussion_votes WHERE discussion_id = :id"
                " AND participant_id = :participant ORDER BY round_number DESC, rowid DESC LIMIT 1"
            ),
            {"id": discussion_id, "participant": participant_id},
        ).first()
        return str(row[0]) if row else None

    def run_round(
        self,
        board_id: str,
        discussion_id: str,
        *,
        run_id: str,
        round_number: int,
        token_budget: int | None,
    ) -> dict[str, Any]:
        """Execute one round and report what happened; the caller decides what comes next."""
        started = time.monotonic()
        with self.boards.reader(board_id) as conn:
            thread_row = conn.execute(
                text("SELECT * FROM discussion_threads WHERE id = :id"), {"id": discussion_id}
            ).mappings().first()
            if thread_row is None:
                raise NotFound("Discussion not found")
            thread = dict(thread_row)
            participants = _rows(
                conn,
                "SELECT * FROM discussion_participants WHERE discussion_id = :id"
                " ORDER BY joined_at",
                {"id": discussion_id},
            )
            messages = self._context(conn, thread)

        registry = self.board_service.registry
        _, tokens_before = self._run_state(board_id, run_id)
        answers = 0
        repeats = 0
        tokens = 0
        failures: list[dict[str, str]] = []
        interrupted: str | None = None
        budget_hit = False

        def emit(event: dict[str, Any] | None) -> None:
            if event is not None and self.events is not None:
                self.events.publish(board_id, event)

        def record(
            conn: Any, type: str, payload: dict[str, Any]
        ) -> dict[str, Any] | None:
            if self.events is None:
                return None
            return self.events.record(
                conn, discussion_id=discussion_id, type=type, payload=payload
            )

        for participant in participants:
            status, _ = self._run_state(board_id, run_id)
            if status != "running":
                interrupted = status
                break
            agent_row = registry.read_one(
                "SELECT * FROM agents WHERE id = :id", {"id": participant["participant_id"]}
            )
            if agent_row is None:
                failures.append({"agent": participant["display_name"], "error": "agent_missing"})
                continue
            with self.boards.session(board_id) as conn:
                started_event = record(
                    conn,
                    AGENT_STARTED,
                    {
                        "participant_id": participant["participant_id"],
                        "agent": participant["display_name"],
                        "round_number": round_number,
                    },
                )
            emit(started_event)
            call_started = time.monotonic()
            result = runtime.call_agent(
                self.settings,
                agent_row,
                system_prompt=participant["system_prompt"],
                messages=messages,
            )
            duration_ms = int((time.monotonic() - call_started) * 1000)
            if not result["ok"]:
                failures.append(
                    {"agent": participant["display_name"], "error": str(result["error"])}
                )
                with self.boards.session(board_id) as conn:
                    failed_event = record(
                        conn,
                        AGENT_FAILED,
                        {
                            "participant_id": participant["participant_id"],
                            "agent": participant["display_name"],
                            "round_number": round_number,
                            "error": str(result["error"]),
                            "duration_ms": duration_ms,
                        },
                    )
                emit(failed_event)
                continue
            digest = content_hash(result["text"])
            round_tokens = usage_tokens(result)
            tokens += round_tokens
            now = utcnow()
            message_event: dict[str, Any] | None = None
            vote_event: dict[str, Any] | None = None
            completed_event: dict[str, Any] | None = None
            with self.boards.session(board_id) as conn:
                previous = conn.execute(
                    text(
                        "SELECT content_sha256 FROM discussion_messages"
                        " WHERE discussion_id = :id AND author_actor_id = :actor"
                        " AND deleted_at IS NULL ORDER BY created_at DESC, rowid DESC LIMIT 1"
                    ),
                    {"id": discussion_id, "actor": participant["participant_id"]},
                ).first()
                if previous is not None and previous[0] == digest:
                    repeats += 1
                else:
                    message_id = str(uuid4())
                    conn.execute(
                        text(
                            "INSERT INTO discussion_messages"
                            " (id, discussion_id, parent_message_id, author_actor_id, author_type,"
                            "  author_name, author_role, content, status, model, round_number,"
                            "  content_sha256, created_at, deleted_at)"
                            " VALUES (:id, :discussion_id, NULL, :actor_id, 'agent', :name, :role,"
                            "         :content, 'posted', :model, :round, :digest, :now, NULL)"
                        ),
                        {
                            "id": message_id,
                            "discussion_id": discussion_id,
                            "actor_id": participant["participant_id"],
                            "name": participant["display_name"],
                            "role": participant["role_template_name"],
                            "content": result["text"],
                            "model": result.get("model"),
                            "round": round_number,
                            "digest": digest,
                            "now": now,
                        },
                    )
                    message_event = record(
                        conn,
                        MESSAGE_CREATED,
                        {
                            "message_id": message_id,
                            "author_actor_id": participant["participant_id"],
                            "author_type": "agent",
                            "author_name": participant["display_name"],
                            "author_role": participant["role_template_name"],
                            "round_number": round_number,
                            "model": result.get("model"),
                            "position": result["verdict"],
                            "content": result["text"],
                        },
                    )
                    previous_position = self._latest_position(
                        conn, discussion_id, participant["participant_id"]
                    )
                    if previous_position != result["verdict"]:
                        conn.execute(
                            text(
                                "INSERT INTO discussion_votes"
                                " (id, discussion_id, participant_id, position, justification,"
                                "  round_number, created_at)"
                                " VALUES (:id, :discussion_id, :participant_id, :position,"
                                "         :justification, :round, :now)"
                            ),
                            {
                                "id": str(uuid4()),
                                "discussion_id": discussion_id,
                                "participant_id": participant["participant_id"],
                                "position": result["verdict"],
                                "justification": result["justification"],
                                "round": round_number,
                                "now": now,
                            },
                        )
                        vote_event = record(
                            conn,
                            VOTE_RECORDED,
                            {
                                "participant_id": participant["participant_id"],
                                "agent": participant["display_name"],
                                "position": result["verdict"],
                                "round_number": round_number,
                            },
                        )
                    answers += 1
                conn.execute(
                    text(
                        "UPDATE discussion_runs SET tokens_used = tokens_used + :tokens"
                        " WHERE id = :id"
                    ),
                    {"tokens": round_tokens, "id": run_id},
                )
                completed_event = record(
                    conn,
                    AGENT_COMPLETED,
                    {
                        "participant_id": participant["participant_id"],
                        "agent": participant["display_name"],
                        "round_number": round_number,
                        "position": result["verdict"],
                        "tokens": round_tokens,
                        "duplicate": message_event is None,
                        "duration_ms": duration_ms,
                    },
                )
            emit(message_event)
            emit(vote_event)
            emit(completed_event)
            if token_budget is not None and tokens_before + tokens > token_budget:
                budget_hit = True
                break

        with self.boards.reader(board_id) as conn:
            votes = _rows(
                conn,
                "SELECT participant_id, position FROM discussion_votes"
                " WHERE discussion_id = :id ORDER BY rowid DESC",
                {"id": discussion_id},
            )
        latest: dict[str, str] = {}
        for vote in votes:
            latest.setdefault(vote["participant_id"], vote["position"])
        unanimous = (
            bool(latest)
            and set(latest.values()) == {"agree"}
            and set(latest) == {p["participant_id"] for p in participants}
        )

        return {
            "round_number": round_number,
            "answers": answers,
            "repeats": repeats,
            "failures": failures,
            "tokens": tokens,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "interrupted": interrupted,
            "budget_hit": budget_hit,
            "unanimous": unanimous,
            "participants": len(participants),
            "latest_positions": [
                {"participant_id": key, "position": value} for key, value in latest.items()
            ],
            "card_id": thread["card_id"],
        }

    def positions(self, board_id: str, discussion_id: str) -> list[dict[str, Any]]:
        with self.boards.reader(board_id) as conn:
            return _rows(
                conn,
                "SELECT v.participant_id, p.display_name, v.position, v.justification, v.created_at"
                " FROM discussion_votes v"
                " LEFT JOIN discussion_participants p ON p.participant_id = v.participant_id"
                " WHERE v.discussion_id = :id ORDER BY v.created_at",
                {"id": discussion_id},
            )
