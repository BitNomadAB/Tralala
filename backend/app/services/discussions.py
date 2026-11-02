from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailure
from ..schemas.discussions import DiscussionCreate, DiscussionMessageCreate
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import require_mutable_card
from .events import HUMAN_REVIEW_COMPLETED, MESSAGE_CREATED, STATUS_CHANGED
from .mentions import extract_mentions

REVIEW_DECISIONS = {"approve": "approved", "veto": "vetoed", "rework": "rework_requested"}
# A human message starts one round in these modes; manual threads wait for an explicit run.
AUTO_RUN_MODES = frozenset({"roundtable", "autonomous"})
AGENT_TRIGGER = re.compile(r"(?<![\w.-])@agents?\b", re.IGNORECASE)


def requests_agent_reply(content: str, participants: list[dict[str, Any]]) -> bool:
    """`@agents` or a participant's name asks the thread to answer, whatever the mode."""
    if AGENT_TRIGGER.search(content):
        return True
    names = [
        {"id": str(participant["participant_id"]), "name": str(participant["display_name"])}
        for participant in participants
    ]
    return bool(extract_mentions(content, names))


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(text(sql), params).mappings()]


class DiscussionService:
    """Ticket-bound discussions. Participants keep an immutable role snapshot."""

    def __init__(self, board_service: BoardService, agent_service: Any) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.agent = agent_service
        self.runs: Any = None
        self.events: Any = None

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

    # --- helpers -------------------------------------------------------------

    def _thread(self, conn: Any, discussion_id: str) -> dict[str, Any]:
        row = conn.execute(
            text("SELECT * FROM discussion_threads WHERE id = :id"), {"id": discussion_id}
        ).mappings().first()
        if row is None:
            raise NotFound("Discussion not found")
        return dict(row)

    def serialize(
        self,
        conn: Any,
        thread: dict[str, Any],
        *,
        with_detail: bool = False,
    ) -> dict[str, Any]:
        entry = dict(thread)
        entry["participant_count"] = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM discussion_participants WHERE discussion_id = :id"
                ),
                {"id": thread["id"]},
            ).scalar_one()
        )
        entry["message_count"] = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM discussion_messages"
                    " WHERE discussion_id = :id AND deleted_at IS NULL"
                ),
                {"id": thread["id"]},
            ).scalar_one()
        )
        card = conn.execute(
            text(
                "SELECT c.title, c.ticket_key, c.loop_id, l.key, l.name"
                " FROM cards c JOIN loops l ON l.id = c.loop_id WHERE c.id = :id"
            ),
            {"id": thread["card_id"]},
        ).first()
        entry["card_title"] = card[0] if card else None
        entry["ticket_key"] = card[1] if card else None
        entry["loop_id"] = card[2] if card else None
        entry["loop_key"] = card[3] if card else None
        entry["loop_name"] = card[4] if card else None
        entry["round_count"] = int(entry.get("round_count") or 0)
        entry["tokens_used"] = int(entry.get("tokens_used") or 0)
        entry["elapsed_ms"] = int(entry.get("elapsed_ms") or 0)
        entry["run_state"] = entry.get("run_state") or "idle"
        if with_detail:
            entry["participants"] = _rows(
                conn,
                "SELECT * FROM discussion_participants WHERE discussion_id = :id"
                " ORDER BY joined_at",
                {"id": thread["id"]},
            )
            entry["messages"] = _rows(
                conn,
                "SELECT * FROM discussion_messages WHERE discussion_id = :id"
                " AND deleted_at IS NULL ORDER BY created_at",
                {"id": thread["id"]},
            )
            entry["votes"] = _rows(
                conn,
                "SELECT v.participant_id, p.display_name, v.position, v.justification,"
                " v.round_number, v.created_at FROM discussion_votes v"
                " LEFT JOIN discussion_participants p ON p.participant_id = v.participant_id"
                " WHERE v.discussion_id = :id ORDER BY v.created_at, v.rowid",
                {"id": thread["id"]},
            )
            entry["runs"] = (
                self.runs.recent(conn, thread["id"]) if self.runs is not None else []
            )
            entry["active_run"] = next(
                (
                    run
                    for run in entry["runs"]
                    if run["status"] in {"running", "paused"}
                ),
                None,
            )
        return entry

    def review(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Human-only final decision. Approving never executes ticket changes."""
        actor.require("discussions:admin")
        if not actor.is_user:
            raise Forbidden("Only a human reviewer can decide a discussion")
        target = REVIEW_DECISIONS.get(decision)
        if target is None:
            raise ValidationFailure("Unknown review decision", details={"decision": decision})
        if decision in {"veto", "rework"} and not reason.strip():
            raise ValidationFailure(
                "An explanation is required for this decision", details={"field": "reason"}
            )
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            thread = self._thread(conn, discussion_id)
            if thread["status"] in {"approved", "vetoed", "cancelled"}:
                raise Conflict(
                    "Discussion is already closed", details={"status": thread["status"]}
                )
            if self.runs is not None and self.runs.active_run(conn, discussion_id) is not None:
                raise Conflict("A run is still active; stop it before reviewing")
            if thread["status"] not in {"consensus_proposed", "human_review", "discussing"}:
                raise Conflict(
                    "Discussion is not ready for review",
                    details={"status": thread["status"]},
                )
            conn.execute(
                text(
                    "UPDATE discussion_threads SET status = :status, updated_at = :now,"
                    " last_activity_at = :now WHERE id = :id"
                ),
                {"status": target, "now": now, "id": discussion_id},
            )
            conn.execute(
                text(
                    "INSERT INTO discussion_outcomes"
                    " (id, discussion_id, summary, payload_json, created_at)"
                    " VALUES (:id, :discussion_id, :summary, :payload, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "discussion_id": discussion_id,
                    "summary": f"{decision} by {actor.actor_name}"
                    + (f": {reason.strip()}" if reason.strip() else ""),
                    "payload": json.dumps(
                        {"decision": decision, "reason": reason.strip(), "actor_id": actor.actor_id}
                    ),
                    "now": now,
                },
            )
            log_activity(
                conn,
                actor,
                action="discussion.reviewed",
                entity_type="card",
                entity_id=thread["card_id"],
                changes={"discussion_id": discussion_id, "decision": decision},
            )
            review_event = self._record(
                conn,
                discussion_id,
                HUMAN_REVIEW_COMPLETED,
                {"decision": decision, "reason": reason.strip(), "status": target},
                actor,
            )
            status_event = self._record(
                conn,
                discussion_id,
                STATUS_CHANGED,
                {"status": target, "run_state": "idle"},
                actor,
            )
        self._publish(board_id, review_event, status_event)
        return self.get(board_id, discussion_id)

    # --- queries -------------------------------------------------------------

    def list(
        self, board_id: str, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.board_service.require_row(board_id)
        clause = " WHERE status = :status" if status else ""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        with self.boards.reader(board_id) as conn:
            threads = _rows(
                conn,
                f"SELECT * FROM discussion_threads{clause}"
                " ORDER BY last_activity_at DESC LIMIT :limit",
                params,
            )
            return [self.serialize(conn, thread) for thread in threads]

    def get(self, board_id: str, discussion_id: str) -> dict[str, Any]:
        self.board_service.require_row(board_id)
        with self.boards.reader(board_id) as conn:
            return self.serialize(conn, self._thread(conn, discussion_id), with_detail=True)

    def _board_counts(self, board_id: str) -> dict[str, Any]:
        """Threads and Tickets for one board, in a single read.

        The discussion dialog offers a board first and then its Tickets, so a board with no Tickets
        has to be visible as such without opening it. One statement covers both counts.
        """
        empty = {
            "discussion_count": 0,
            "open_count": 0,
            "last_activity_at": None,
            "ticket_count": 0,
        }
        try:
            with self.boards.reader(board_id) as conn:
                row = conn.execute(
                    text(
                        "SELECT"
                        " (SELECT COUNT(*) FROM cards WHERE archived_at IS NULL) AS ticket_count,"
                        " MAX(last_activity_at) AS last_activity_at,"
                        " COUNT(*) AS discussion_count,"
                        " COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0)"
                        " AS open_count"
                        " FROM discussion_threads"
                    )
                ).mappings().first()
        except (NotFound, ServiceUnavailable):
            # A board whose schema is mid-repair must still appear in the overview.
            return empty
        if row is None:
            return empty
        return {
            "discussion_count": int(row["discussion_count"] or 0),
            "open_count": int(row["open_count"] or 0),
            "last_activity_at": row["last_activity_at"],
            "ticket_count": int(row["ticket_count"] or 0),
        }

    def board_overview(self) -> list[dict[str, Any]]:
        """One entrance per board, newest discussion activity first.

        The browser only needs this summary to pick a board; threads are fetched for the selected
        board alone. Boards without threads sort last, alphabetically, so an empty board is still
        reachable.
        """
        entries = [
            {
                "board_id": board["id"],
                "board_name": board["name"],
                "status": board["status"],
                **self._board_counts(board["id"]),
            }
            for board in self.board_service.registry.read(
                "SELECT id, name, status FROM boards"
            )
        ]
        entries.sort(key=lambda entry: entry["board_name"].casefold())
        entries.sort(key=lambda entry: entry["last_activity_at"] or "", reverse=True)
        return entries

    # --- commands ------------------------------------------------------------

    def create(
        self, actor: ActorContext, board_id: str, payload: DiscussionCreate
    ) -> dict[str, Any]:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        discussion_id = str(uuid4())
        with self.boards.session(board_id) as conn:
            card = conn.execute(
                text("SELECT id, title FROM cards WHERE id = :id AND archived_at IS NULL"),
                {"id": payload.card_id},
            ).mappings().first()
            if card is None:
                raise ValidationFailure(
                    "Discussion must reference an existing ticket",
                    details={"card_id": payload.card_id},
                )
            require_mutable_card(conn, payload.card_id)
            title = (payload.title or f"{card['title']} — discussion").strip()
            conn.execute(
                text(
                    "INSERT INTO discussion_threads"
                    " (id, card_id, title, goal, mode, status, created_by_actor_id,"
                    "  created_by_type, created_by_name, max_rounds, origin_comment_id,"
                    "  escalation_depth, created_at, updated_at, last_activity_at)"
                    " VALUES (:id, :card_id, :title, :goal, :mode, 'open', :actor_id,"
                    "         :actor_type, :actor_name, :max_rounds, NULL, 0, :now, :now, :now)"
                ),
                {
                    "id": discussion_id,
                    "card_id": payload.card_id,
                    "title": title,
                    "goal": payload.goal,
                    "mode": payload.mode,
                    "actor_id": actor.actor_id,
                    "actor_type": actor.actor_type,
                    "actor_name": actor.actor_name,
                    "max_rounds": payload.max_rounds,
                    "now": now,
                },
            )
            self._add_participants(conn, discussion_id, payload.participant_ids, now)
            conn.execute(
                text(
                    "INSERT INTO discussion_messages"
                    " (id, discussion_id, parent_message_id, author_actor_id, author_type,"
                    "  author_name, author_role, content, status, model, created_at, deleted_at)"
                    " VALUES (:id, :discussion_id, NULL, :actor_id, :actor_type, :actor_name,"
                    "         NULL, :content, 'posted', NULL, :now, NULL)"
                ),
                {
                    "id": str(uuid4()),
                    "discussion_id": discussion_id,
                    "actor_id": actor.actor_id,
                    "actor_type": actor.actor_type,
                    "actor_name": actor.actor_name,
                    "content": payload.goal,
                    "now": now,
                },
            )
            log_activity(
                conn,
                actor,
                action="discussion.created",
                entity_type="card",
                entity_id=payload.card_id,
                changes={"discussion_id": discussion_id, "title": title},
            )
        return self.get(board_id, discussion_id)

    def _add_participants(
        self, conn: Any, discussion_id: str, participant_ids: list[str], now: str
    ) -> None:
        agents = self.board_service.registry
        for participant_id in participant_ids:
            row = agents.read_one(
                "SELECT id, name, enabled FROM agents WHERE id = :id", {"id": participant_id}
            )
            if row is None or not row["enabled"]:
                raise ValidationFailure(
                    "Participant must be an enabled agent",
                    details={"participant_id": participant_id},
                )
            snapshot = self.agent.role_snapshot(row["id"])
            conn.execute(
                text(
                    "INSERT INTO discussion_participants"
                    " (id, discussion_id, participant_id, participant_type, display_name,"
                    "  role_template_id, role_template_name, role_template_updated_at,"
                    "  role_source, system_prompt, system_prompt_sha256, snapshot_at, joined_at)"
                    " VALUES (:id, :discussion_id, :participant_id, 'agent', :name, :template_id,"
                    "         :template_name, :template_updated, :source, :prompt, :prompt_hash,"
                    "         :now, :now)"
                ),
                {
                    "id": str(uuid4()),
                    "discussion_id": discussion_id,
                    "participant_id": row["id"],
                    "name": row["name"],
                    "template_id": snapshot["role_template_id"],
                    "template_name": snapshot["role_template_name"],
                    "template_updated": snapshot["role_template_updated_at"],
                    "source": snapshot["role_source"],
                    "prompt": snapshot["system_prompt"],
                    "prompt_hash": snapshot["system_prompt_sha256"],
                    "now": now,
                },
            )

    def add_message(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        payload: DiscussionMessageCreate,
    ) -> dict[str, Any]:
        actor.require("discussions:write")
        self.board_service.ensure_active(board_id)
        now = utcnow()
        with self.boards.session(board_id) as conn:
            thread = self._thread(conn, discussion_id)
            if payload.parent_message_id:
                parent = conn.execute(
                    text(
                        "SELECT id FROM discussion_messages"
                        " WHERE id = :id AND discussion_id = :discussion_id"
                    ),
                    {"id": payload.parent_message_id, "discussion_id": discussion_id},
                ).first()
                if parent is None:
                    raise ValidationFailure("Parent message does not belong to this discussion")
            message_id = str(uuid4())
            conn.execute(
                text(
                    "INSERT INTO discussion_messages"
                    " (id, discussion_id, parent_message_id, author_actor_id, author_type,"
                    "  author_name, author_role, content, status, model, created_at, deleted_at)"
                    " VALUES (:id, :discussion_id, :parent, :actor_id, :actor_type, :actor_name,"
                    "         NULL, :content, 'posted', NULL, :now, NULL)"
                ),
                {
                    "id": message_id,
                    "discussion_id": discussion_id,
                    "parent": payload.parent_message_id,
                    "actor_id": actor.actor_id,
                    "actor_type": actor.actor_type,
                    "actor_name": actor.actor_name,
                    "content": payload.content,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "UPDATE discussion_threads SET updated_at = :now, last_activity_at = :now,"
                    " status = CASE WHEN status = 'open' THEN 'discussing' ELSE status END"
                    " WHERE id = :id"
                ),
                {"now": now, "id": discussion_id},
            )
            log_activity(
                conn,
                actor,
                action="discussion.message_posted",
                entity_type="card",
                entity_id=thread["card_id"],
                changes={"discussion_id": discussion_id, "message_id": message_id},
            )
            participants = _rows(
                conn,
                "SELECT participant_id, display_name FROM discussion_participants"
                " WHERE discussion_id = :id ORDER BY joined_at",
                {"id": discussion_id},
            )
            message_event = self._record(
                conn,
                discussion_id,
                MESSAGE_CREATED,
                {
                    "message_id": message_id,
                    "parent_message_id": payload.parent_message_id,
                    "author_actor_id": actor.actor_id,
                    "author_type": actor.actor_type,
                    "author_name": actor.actor_name,
                    "content": payload.content,
                },
                actor,
            )
        self._publish(board_id, message_event)
        auto_run = self._auto_run(
            actor, board_id, discussion_id, thread["mode"], payload.content, participants
        )
        detail = self.get(board_id, discussion_id)
        detail["auto_run"] = auto_run
        return detail

    def _auto_run(
        self,
        actor: ActorContext,
        board_id: str,
        discussion_id: str,
        mode: str,
        content: str,
        participants: list[dict[str, Any]],
    ) -> str | None:
        """Answer a human message automatically when the thread asks for it.

        In roundtable/autonomous threads every human message starts one background round. In a
        manual thread the message must opt in with `@agents` or a participant's name. One round is
        the least surprising spend; a thread that is closed or already running keeps the message,
        and the post itself never fails because no run could be started. Returns what happened so
        the client can explain a skipped answer.
        """
        if self.runs is None or not actor.is_user:
            return None
        if mode not in AUTO_RUN_MODES and not requests_agent_reply(content, participants):
            return None
        try:
            self.runs.start(
                actor, board_id, discussion_id, rounds=1, autonomous=False, background=True
            )
        except Conflict as exc:
            details = exc.details if isinstance(exc.details, dict) else {}
            return "already_running" if details.get("run_id") else "thread_closed"
        except ValidationFailure:
            return "no_participants"
        return "started"

