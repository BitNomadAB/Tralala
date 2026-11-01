"""Structured RoadMaps: validation, identity reservation, publication and readiness.

The structured plan revision is authoritative. ``loop_phases``, ``loop_plan_items`` and
``loop_dependencies`` are validated projections that carry stable identities; live cards are the
execution projection of the active plan.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

from ..core.context import ActorContext
from ..core.errors import Conflict, NotFound, ValidationFailure
from ..schemas.loops import PlanPayload, PlanTicket
from ..storage.sqlite import utcnow
from .activity import log_activity
from .boards import BoardService
from .common import one, rows
from .loop_identifiers import format_ticket_key, phase_prefix
from .loops import LoopService


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (TypeError, ValueError):
        return False
    return True


class LoopPlanService:
    def __init__(self, board_service: BoardService, loop_service: LoopService) -> None:
        self.board_service = board_service
        self.boards = board_service.boards
        self.loops = loop_service

    # --- validation ------------------------------------------------------------

    def validate(self, payload: PlanPayload) -> None:
        """Reject malformed identities, broken references and dependency cycles early."""
        phase_ids: set[str] = set()
        numbers: set[int] = set()
        ticket_ids: set[str] = set()
        for phase in payload.phases:
            if not _is_uuid(phase.id):
                raise ValidationFailure(
                    "Phase ids must be UUIDs so identities survive replanning",
                    code="invalid_dependency_graph",
                    details={"phase_id": phase.id},
                )
            if phase.id in phase_ids:
                raise ValidationFailure(
                    "Duplicate phase id",
                    code="invalid_dependency_graph",
                    details={"phase_id": phase.id},
                )
            if phase.number in numbers:
                raise ValidationFailure(
                    "Duplicate phase number",
                    code="invalid_dependency_graph",
                    details={"phase_number": phase.number},
                )
            phase_ids.add(phase.id)
            numbers.add(phase.number)
            for ticket in phase.tickets:
                if not _is_uuid(ticket.id):
                    raise ValidationFailure(
                        "Ticket ids must be UUIDs so identities survive replanning",
                        code="invalid_dependency_graph",
                        details={"ticket_id": ticket.id},
                    )
                if ticket.id in ticket_ids:
                    raise ValidationFailure(
                        "Duplicate ticket id",
                        code="invalid_dependency_graph",
                        details={"ticket_id": ticket.id},
                    )
                ticket_ids.add(ticket.id)

        tickets: dict[str, PlanTicket] = {
            ticket.id: ticket for phase in payload.phases for ticket in phase.tickets
        }
        phase_of_ticket: dict[str, str] = {
            ticket.id: phase.id for phase in payload.phases for ticket in phase.tickets
        }
        if not tickets:
            raise ValidationFailure(
                "A RoadMap must contain at least one planned Ticket",
                code="invalid_dependency_graph",
            )

        for phase in payload.phases:
            for reference in (*phase.prerequisite_phase_ids, *phase.prerequisite_ticket_ids):
                if reference == phase.id:
                    raise ValidationFailure(
                        "A Phase cannot depend on itself",
                        code="invalid_dependency_graph",
                        details={"phase_id": phase.id},
                    )
            for reference in phase.prerequisite_phase_ids:
                if reference not in phase_ids:
                    raise ValidationFailure(
                        "Phase dependency references an unknown Phase",
                        code="invalid_dependency_graph",
                        details={"phase_id": phase.id, "missing": reference},
                    )
            for reference in phase.prerequisite_ticket_ids:
                if reference not in ticket_ids:
                    raise ValidationFailure(
                        "Phase dependency references an unknown Ticket",
                        code="invalid_dependency_graph",
                        details={"phase_id": phase.id, "missing": reference},
                    )
            for ticket in phase.tickets:
                self._validate_ticket(ticket, phase_ids, ticket_ids)

        self._reject_cycles(payload, tickets, phase_of_ticket)

    @staticmethod
    def _validate_ticket(ticket: PlanTicket, phase_ids: set[str], ticket_ids: set[str]) -> None:
        if ticket.id in ticket.prerequisite_ticket_ids:
            raise ValidationFailure(
                "A Ticket cannot depend on itself",
                code="invalid_dependency_graph",
                details={"ticket_id": ticket.id},
            )
        for reference in ticket.prerequisite_phase_ids:
            if reference not in phase_ids:
                raise ValidationFailure(
                    "Ticket dependency references an unknown Phase",
                    code="invalid_dependency_graph",
                    details={"ticket_id": ticket.id, "missing": reference},
                )
        for reference in ticket.prerequisite_ticket_ids:
            if reference not in ticket_ids:
                raise ValidationFailure(
                    "Ticket dependency references an unknown Ticket",
                    code="invalid_dependency_graph",
                    details={"ticket_id": ticket.id, "missing": reference},
                )
        if ticket.required_actor == "human":
            if not ticket.human_action_reason.strip() or not ticket.human_instructions.strip():
                raise ValidationFailure(
                    "A human-only Ticket needs a reason and instructions",
                    code="invalid_dependency_graph",
                    details={"ticket_id": ticket.id},
                )
        if ticket.execution_mode == "pre_phase_gate" and ticket.prerequisite_phase_ids:
            own_phase_gate = ticket.id
            del own_phase_gate

    @staticmethod
    def _reject_cycles(
        payload: PlanPayload,
        tickets: dict[str, PlanTicket],
        phase_of_ticket: dict[str, str],
    ) -> None:
        """Cycle detection that includes implicit ordinary-Ticket-to-Phase relationships."""
        graph: dict[str, set[str]] = {}
        for phase in payload.phases:
            node = f"phase:{phase.id}"
            graph.setdefault(node, set())
            graph[node].update(f"phase:{other}" for other in phase.prerequisite_phase_ids)
            graph[node].update(f"ticket:{other}" for other in phase.prerequisite_ticket_ids)
        for ticket in tickets.values():
            node = f"ticket:{ticket.id}"
            graph.setdefault(node, set())
            graph[node].update(f"ticket:{other}" for other in ticket.prerequisite_ticket_ids)
            graph[node].update(f"phase:{other}" for other in ticket.prerequisite_phase_ids)
            if ticket.execution_mode == "normal":
                graph[node].add(f"phase:{phase_of_ticket[ticket.id]}")

        state: dict[str, int] = {}

        def visit(node: str, path: list[str]) -> None:
            if state.get(node) == 1:
                raise ValidationFailure(
                    "Plan dependency graph contains a cycle",
                    code="invalid_dependency_graph",
                    details={"cycle": path + [node]},
                )
            if state.get(node) == 2:
                return
            state[node] = 1
            for target in sorted(graph.get(node, ())):
                visit(target, path + [node])
            state[node] = 2

        for node in sorted(graph):
            visit(node, [])

    # --- identity reservation --------------------------------------------------

    def next_ticket_sequence(self, conn: Any, loop_id: str, phase_number: int) -> int:
        value = conn.execute(
            text(
                "SELECT COALESCE(MAX(ticket_sequence), 0) FROM loop_plan_items"
                " WHERE loop_id = :loop_id AND phase_number = :number"
            ),
            {"loop_id": loop_id, "number": phase_number},
        ).scalar_one()
        return int(value) + 1

    def _known_phase(self, conn: Any, loop_id: str, phase_id: str) -> dict[str, Any] | None:
        return one(
            conn,
            "SELECT * FROM loop_phases WHERE loop_id = :loop_id AND id = :id",
            {"loop_id": loop_id, "id": phase_id},
        )

    def _known_item(self, conn: Any, loop_id: str, item_id: str) -> dict[str, Any] | None:
        return one(
            conn,
            "SELECT * FROM loop_plan_items WHERE loop_id = :loop_id AND id = :id",
            {"loop_id": loop_id, "id": item_id},
        )

    def register_draft(
        self,
        conn: Any,
        loop_row: dict[str, Any],
        payload: PlanPayload,
        actor: ActorContext,
        *,
        source_revisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Validate a candidate, reserve identities and store it as an unapproved plan revision."""
        self.validate(payload)
        loop_id = loop_row["id"]
        loop_key = loop_row["key"]
        revision = int(
            conn.execute(
                text(
                    "SELECT COALESCE(MAX(revision_number), 0) FROM loop_plans WHERE loop_id = :id"
                ),
                {"id": loop_id},
            ).scalar_one()
        ) + 1
        plan_id = str(uuid.uuid4())
        now = utcnow()
        canonical = self._canonical_payload(conn, loop_row, payload, plan_id, revision)
        conn.execute(
            text(
                "INSERT INTO loop_plans (id, loop_id, revision_number, roadmap_ai_revision_id,"
                " roadmap_revision_id, approval_id, payload_json, content_hash, status, created_at)"
                " VALUES (:id, :loop_id, :revision, :ai_revision, :human_revision, NULL, :payload,"
                " :hash, 'draft', :now)"
            ),
            {
                "id": plan_id,
                "loop_id": loop_id,
                "revision": revision,
                "ai_revision": (source_revisions or {}).get("roadmap_ai", ""),
                "human_revision": (source_revisions or {}).get("roadmap", ""),
                "payload": json.dumps(canonical),
                "hash": self._hash(canonical),
                "now": now,
            },
        )
        self._project(conn, loop_row, plan_id, canonical, actor)
        del loop_key
        return {
            "plan_id": plan_id,
            "revision_number": revision,
            "payload": canonical,
        }

    def _canonical_payload(
        self,
        conn: Any,
        loop_row: dict[str, Any],
        payload: PlanPayload,
        plan_id: str,
        revision: int,
    ) -> dict[str, Any]:
        """Attach server-allocated keys and phase numbers to the model's structure."""
        phases: list[dict[str, Any]] = []
        counters: dict[int, int] = {}
        for phase in sorted(payload.phases, key=lambda entry: entry.number):
            tickets: list[dict[str, Any]] = []
            for ticket in phase.tickets:
                known_item = self._known_item(conn, loop_row["id"], ticket.id)
                if known_item is not None:
                    sequence = known_item["ticket_sequence"]
                    key = known_item["key"]
                else:
                    sequence = counters.get(phase.number)
                    if sequence is None:
                        sequence = self.next_ticket_sequence(conn, loop_row["id"], phase.number)
                    counters[phase.number] = sequence + 1
                    key = format_ticket_key(
                        loop_row["key"], phase_prefix(phase.name), phase.number, sequence
                    )
                tickets.append(
                    {
                        **ticket.model_dump(),
                        "key": key,
                        "sequence": sequence,
                        "phase_number": phase.number,
                    }
                )
            phases.append(
                {
                    **{key: value for key, value in phase.model_dump().items() if key != "tickets"},
                    "tickets": tickets,
                }
            )
        return {
            "schema_version": payload.schema_version,
            "summary": payload.summary,
            "loop_id": loop_row["id"],
            "loop_key": loop_row["key"],
            "plan_id": plan_id,
            "revision_number": revision,
            "phases": phases,
        }

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        import hashlib

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _project(
        self,
        conn: Any,
        loop_row: dict[str, Any],
        plan_id: str,
        canonical: dict[str, Any],
        actor: ActorContext,
    ) -> None:
        loop_id = loop_row["id"]
        now = utcnow()
        conn.execute(text("DELETE FROM loop_dependencies WHERE loop_id = :id"), {"id": loop_id})
        for phase in canonical["phases"]:
            existing = self._known_phase(conn, loop_id, phase["id"])
            if existing is None:
                conn.execute(
                    text(
                        "INSERT INTO loop_phases (id, loop_id, plan_id, number, name, objective,"
                        " entry_conditions_json, exit_conditions_json, is_qa_phase, created_at)"
                        " VALUES (:id, :loop_id, :plan_id, :number, :name, :objective, :entry,"
                        " :exit, 0, :now)"
                    ),
                    {
                        "id": phase["id"],
                        "loop_id": loop_id,
                        "plan_id": plan_id,
                        "number": phase["number"],
                        "name": phase["name"],
                        "objective": phase["objective"],
                        "entry": json.dumps(phase["entry_conditions"]),
                        "exit": json.dumps(phase["exit_conditions"]),
                        "now": now,
                    },
                )
            else:
                conn.execute(
                    text(
                        "UPDATE loop_phases SET plan_id = :plan_id, number = :number,"
                        " name = :name, objective = :objective, entry_conditions_json = :entry,"
                        " exit_conditions_json = :exit WHERE id = :id"
                    ),
                    {
                        "id": phase["id"],
                        "plan_id": plan_id,
                        "number": phase["number"],
                        "name": phase["name"],
                        "objective": phase["objective"],
                        "entry": json.dumps(phase["entry_conditions"]),
                        "exit": json.dumps(phase["exit_conditions"]),
                    },
                )
            for reference in phase["prerequisite_phase_ids"]:
                self._add_edge(
                    conn, loop_id, plan_id, "phase", phase["id"], "phase", reference, now
                )
            for reference in phase["prerequisite_ticket_ids"]:
                self._add_edge(
                    conn, loop_id, plan_id, "phase", phase["id"], "ticket", reference, now
                )
            for ticket in phase["tickets"]:
                self._project_item(conn, loop_id, plan_id, phase, ticket, now)
                for reference in ticket["prerequisite_ticket_ids"]:
                    self._add_edge(
                        conn, loop_id, plan_id, "ticket", ticket["id"], "ticket", reference, now
                    )
                for reference in ticket["prerequisite_phase_ids"]:
                    self._add_edge(
                        conn, loop_id, plan_id, "ticket", ticket["id"], "phase", reference, now
                    )
        log_activity(
            conn,
            actor,
            action="loop.plan_registered",
            entity_type="loop",
            entity_id=loop_id,
            changes={"plan_id": plan_id, "revision": canonical["revision_number"]},
        )

    def _project_item(
        self,
        conn: Any,
        loop_id: str,
        plan_id: str,
        phase: dict[str, Any],
        ticket: dict[str, Any],
        now: str,
    ) -> None:
        existing = self._known_item(conn, loop_id, ticket["id"])
        values = {
            "id": ticket["id"],
            "loop_id": loop_id,
            "plan_id": plan_id,
            "phase_id": phase["id"],
            "phase_number": phase["number"],
            "key": ticket["key"],
            "ticket_sequence": ticket["sequence"],
            "title": ticket["title"],
            "objective": ticket["objective"],
            "instructions": ticket["instructions"],
            "required_actor": ticket["required_actor"],
            "execution_mode": ticket["execution_mode"],
            "priority": ticket["priority"],
            "acceptance": json.dumps(ticket["acceptance_criteria"]),
            "evidence": json.dumps(ticket["expected_evidence"]),
            "human_reason": ticket["human_action_reason"],
            "human_instructions": ticket["human_instructions"],
            "now": now,
        }
        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO loop_plan_items (id, loop_id, plan_id, phase_id, phase_number,"
                    " key, ticket_sequence, title, objective, instructions, required_actor,"
                    " execution_mode, priority, acceptance_criteria_json, expected_evidence_json,"
                    " human_action_reason, human_instructions, created_at)"
                    " VALUES (:id, :loop_id, :plan_id, :phase_id, :phase_number, :key,"
                    " :ticket_sequence, :title, :objective, :instructions, :required_actor,"
                    " :execution_mode, :priority, :acceptance, :evidence, :human_reason,"
                    " :human_instructions, :now)"
                ),
                values,
            )
        else:
            conn.execute(
                text(
                    "UPDATE loop_plan_items SET plan_id = :plan_id, phase_id = :phase_id,"
                    " phase_number = :phase_number, title = :title, objective = :objective,"
                    " instructions = :instructions, required_actor = :required_actor,"
                    " execution_mode = :execution_mode, priority = :priority,"
                    " acceptance_criteria_json = :acceptance, expected_evidence_json = :evidence,"
                    " human_action_reason = :human_reason,"
                    " human_instructions = :human_instructions WHERE id = :id"
                ),
                values,
            )
            self._sync_card(conn, ticket["id"], values)

    def _sync_card(self, conn: Any, item_id: str, values: dict[str, Any]) -> None:
        """Keep an already-materialised card aligned with its retained plan identity."""
        conn.execute(
            text(
                "UPDATE cards SET title = :title, description = :instructions,"
                " required_actor = :required_actor, execution_mode = :execution_mode,"
                " human_action_reason = :human_reason, human_instructions = :human_instructions,"
                " phase_id = :phase_id, updated_at = :now WHERE id = :id AND plan_item_id = :id"
            ),
            values,
        )

    def _add_edge(
        self,
        conn: Any,
        loop_id: str,
        plan_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        now: str,
    ) -> None:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO loop_dependencies (id, loop_id, plan_id, source_type,"
                " source_id, target_type, target_id, created_at)"
                " VALUES (:id, :loop_id, :plan_id, :source_type, :source_id, :target_type,"
                " :target_id, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "loop_id": loop_id,
                "plan_id": plan_id,
                "source_type": source_type,
                "source_id": source_id,
                "target_type": target_type,
                "target_id": target_id,
                "now": now,
            },
        )

    # --- publication -----------------------------------------------------------

    def publish(
        self,
        conn: Any,
        loop_row: dict[str, Any],
        plan_id: str,
        actor: ActorContext,
        *,
        approval_id: str | None,
    ) -> dict[str, Any]:
        """Materialise every planned Ticket in one transaction. All or nothing."""
        loop_id = loop_row["id"]
        plan = one(conn, "SELECT * FROM loop_plans WHERE id = :id", {"id": plan_id})
        if plan is None:
            raise NotFound("Plan not found")
        canonical = json.loads(plan["payload_json"])
        lists = rows(
            conn,
            "SELECT id FROM lists WHERE loop_id = :id AND archived_at IS NULL"
            " ORDER BY position, id LIMIT 1",
            {"id": loop_id},
        )
        if not lists:
            raise Conflict(
                "The Loop has no column to publish Tickets into",
                code="loop_required",
                details={"loop_id": loop_id},
            )
        target_list = lists[0]["id"]
        now = utcnow()
        created: list[dict[str, Any]] = []
        for phase in canonical["phases"]:
            for ticket in phase["tickets"]:
                existing = one(conn, "SELECT * FROM cards WHERE id = :id", {"id": ticket["id"]})
                if existing is not None:
                    if existing["ticket_key"] != ticket["key"]:
                        raise Conflict(
                            "A card with this identity already exists with a different key",
                            code="plan_change_required",
                            details={"ticket_id": ticket["id"]},
                        )
                    created.append({"id": existing["id"], "key": existing["ticket_key"]})
                    continue
                position = conn.execute(
                    text(
                        "SELECT COALESCE(MAX(position), 0) + 1024 FROM cards"
                        " WHERE list_id = :list_id"
                    ),
                    {"list_id": target_list},
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO cards (id, loop_id, list_id, title, description, position,"
                        " priority, created_at, updated_at, version, phase_id, plan_item_id,"
                        " ticket_key, kind, required_actor, execution_mode, human_action_reason,"
                        " human_instructions, plan_revision_id)"
                        " VALUES (:id, :loop_id, :list_id, :title, :description, :position,"
                        " :priority, :now, :now, 1, :phase_id, :id, :key, 'ticket',"
                        " :required_actor, :execution_mode, :human_reason, :human_instructions,"
                        " :plan_id)"
                    ),
                    {
                        "id": ticket["id"],
                        "loop_id": loop_id,
                        "list_id": target_list,
                        "title": ticket["title"],
                        "description": ticket["instructions"],
                        "position": int(position),
                        "priority": ticket["priority"],
                        "phase_id": phase["id"],
                        "key": ticket["key"],
                        "required_actor": ticket["required_actor"],
                        "execution_mode": ticket["execution_mode"],
                        "human_reason": ticket["human_action_reason"],
                        "human_instructions": ticket["human_instructions"],
                        "plan_id": plan_id,
                        "now": now,
                    },
                )
                created.append({"id": ticket["id"], "key": ticket["key"]})
        conn.execute(
            text(
                "UPDATE loop_plans SET status = 'superseded', superseded_at = :now"
                " WHERE loop_id = :loop_id AND status = 'active' AND id != :plan_id"
            ),
            {"now": now, "loop_id": loop_id, "plan_id": plan_id},
        )
        conn.execute(
            text(
                "UPDATE loop_plans SET status = 'active', approval_id = :approval_id,"
                " activated_at = COALESCE(activated_at, :now) WHERE id = :id"
            ),
            {"approval_id": approval_id, "now": now, "id": plan_id},
        )
        conn.execute(
            text(
                "UPDATE loops SET current_plan_id = :plan_id, updated_at = :now WHERE id = :id"
            ),
            {"plan_id": plan_id, "now": now, "id": loop_id},
        )
        log_activity(
            conn,
            actor,
            action="loop.plan_published",
            entity_type="loop",
            entity_id=loop_id,
            changes={"plan_id": plan_id, "tickets": len(created)},
        )
        return {"plan_id": plan_id, "tickets": created}

    def attach_revisions(
        self, conn: Any, plan_id: str, *, roadmap_ai_revision_id: str, roadmap_revision_id: str
    ) -> None:
        conn.execute(
            text(
                "UPDATE loop_plans SET roadmap_ai_revision_id = :ai,"
                " roadmap_revision_id = :human WHERE id = :id"
            ),
            {"ai": roadmap_ai_revision_id, "human": roadmap_revision_id, "id": plan_id},
        )

    # --- views -----------------------------------------------------------------

    def active_plan(self, conn: Any, loop_id: str) -> dict[str, Any] | None:
        return one(
            conn, "SELECT * FROM loop_plans WHERE loop_id = :id AND status = 'active'",
            {"id": loop_id}
        )

    def dependencies(self, conn: Any, loop_id: str) -> dict[str, dict[str, list[str]]]:
        edges = rows(
            conn,
            "SELECT source_type, source_id, target_type, target_id FROM loop_dependencies"
            " WHERE loop_id = :id",
            {"id": loop_id},
        )
        result: dict[str, dict[str, list[str]]] = {}
        for edge in edges:
            node = f"{edge['source_type']}:{edge['source_id']}"
            bucket = result.setdefault(node, {"phases": [], "tickets": []})
            if edge["target_type"] == "phase":
                bucket["phases"].append(edge["target_id"])
            else:
                bucket["tickets"].append(edge["target_id"])
        return result

    def _phase_items(self, conn: Any, loop_id: str) -> dict[str, list[dict[str, Any]]]:
        records = rows(
            conn,
            "SELECT i.*, c.id AS card_id, c.completed_at, c.archived_at, c.human_confirmed_at,"
            " c.version AS card_version FROM loop_plan_items i"
            " LEFT JOIN cards c ON c.plan_item_id = i.id"
            " WHERE i.loop_id = :id ORDER BY i.phase_number, i.ticket_sequence, i.key",
            {"id": loop_id},
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            grouped.setdefault(record["phase_id"], []).append(record)
        return grouped

    def plan_view(
        self,
        conn: Any,
        loop_row: dict[str, Any],
        *,
        include_readiness: bool = True,
    ) -> dict[str, Any]:
        loop_id = loop_row["id"]
        plan = self.active_plan(conn, loop_id)
        if plan is None:
            return {
                "loop_id": loop_id,
                "plan_id": None,
                "revision_number": None,
                "status": "none",
                "activated_at": None,
                "approved_at": None,
                "phases": [],
                "warnings": [],
            }
        phases = rows(
            conn,
            "SELECT * FROM loop_phases WHERE loop_id = :id ORDER BY number",
            {"id": loop_id},
        )
        items = self._phase_items(conn, loop_id)
        dependencies = self.dependencies(conn, loop_id)
        readiness = (
            self._evaluate(loop_row, phases, items, dependencies) if include_readiness else {}
        )
        view = {
            "loop_id": loop_id,
            "plan_id": plan["id"],
            "revision_number": plan["revision_number"],
            "status": plan["status"],
            "activated_at": plan["activated_at"],
            "approved_at": plan["activated_at"],
            "phases": readiness.get("phases", []),
            "warnings": readiness.get("warnings", []),
        }
        return view

    def readiness(self, conn: Any, loop_row: dict[str, Any]) -> dict[str, Any]:
        plan = self.active_plan(conn, loop_row["id"])
        if plan is None:
            return {
                "loop_id": loop_row["id"],
                "stage": loop_row["stage"],
                "execution_allowed": False,
                "blocked_reason": {
                    "code": "approval_required",
                    "message": "No approved plan has been published for this Loop",
                },
                "items": [],
                "phases": [],
            }
        phases = rows(
            conn,
            "SELECT * FROM loop_phases WHERE loop_id = :id ORDER BY number",
            {"id": loop_row["id"]},
        )
        items = self._phase_items(conn, loop_row["id"])
        dependencies = self.dependencies(conn, loop_row["id"])
        evaluation = self._evaluate(loop_row, phases, items, dependencies)
        execution_allowed = loop_row["stage"] in {"ready", "in_progress", "awaiting_qa"}
        blocked_reason = None
        if not execution_allowed:
            blocked_reason = {
                "code": "plan_change_required"
                if loop_row["stage"] == "replanning"
                else "approval_required",
                "message": "Execution transitions are frozen for this Loop stage",
                "stage": loop_row["stage"],
            }
        return {
            "loop_id": loop_row["id"],
            "stage": loop_row["stage"],
            "execution_allowed": execution_allowed,
            "blocked_reason": blocked_reason,
            "items": [item for phase in evaluation["phases"] for item in phase["tickets"]],
            "phases": evaluation["phases"],
        }

    def _evaluate(
        self,
        loop_row: dict[str, Any],
        phases: list[dict[str, Any]],
        items_by_phase: dict[str, list[dict[str, Any]]],
        dependencies: dict[str, dict[str, list[str]]],
    ) -> dict[str, Any]:
        loop_id = loop_row["id"]
        phase_by_id = {phase["id"]: phase for phase in phases}
        item_lookup: dict[str, dict[str, Any]] = {
            item["id"]: item for values in items_by_phase.values() for item in values
        }
        completed_items = {
            item_id
            for item_id, item in item_lookup.items()
            if item.get("completed_at") is not None
        }
        phase_complete: dict[str, bool] = {}
        phase_entered: dict[str, bool] = {}
        warnings: list[dict[str, Any]] = []

        def phase_dependencies(phase_id: str) -> dict[str, list[str]]:
            return dependencies.get(f"phase:{phase_id}", {"phases": [], "tickets": []})

        def item_dependencies(item_id: str) -> dict[str, list[str]]:
            return dependencies.get(f"ticket:{item_id}", {"phases": [], "tickets": []})

        def gates_in(phase_id: str) -> list[dict[str, Any]]:
            return [
                item
                for item in items_by_phase.get(phase_id, [])
                if item["execution_mode"] == "pre_phase_gate"
            ]

        def compute_phase_complete(phase_id: str) -> bool:
            entries = items_by_phase.get(phase_id, [])
            if not entries:
                return all(
                    phase_complete.get(reference, False)
                    for reference in phase_dependencies(phase_id)["phases"]
                )
            return all(item["completed_at"] is not None for item in entries)

        def blockers_for(
            phase_ids: list[str], ticket_ids: list[str], *, include_gates_of: str | None
        ) -> list[dict[str, Any]]:
            blockers: list[dict[str, Any]] = []
            for reference in phase_ids:
                if not phase_complete.get(reference, False):
                    phase = phase_by_id.get(reference, {})
                    blockers.append(
                        {
                            "type": "phase",
                            "id": reference,
                            "reason": "prerequisite_phase_incomplete",
                            "phase_number": phase.get("number"),
                            "name": phase.get("name", ""),
                        }
                    )
            for reference in ticket_ids:
                if reference not in completed_items:
                    item = item_lookup.get(reference, {})
                    blockers.append(
                        {
                            "type": "ticket",
                            "id": reference,
                            "key": item.get("key"),
                            "title": item.get("title", ""),
                            "reason": "prerequisite_ticket_incomplete",
                        }
                    )
            if include_gates_of is not None:
                for gate in gates_in(include_gates_of):
                    if gate["completed_at"] is None:
                        blockers.append(
                            {
                                "type": "ticket",
                                "id": gate["id"],
                                "key": gate["key"],
                                "title": gate["title"],
                                "reason": "pre_phase_gate_incomplete",
                            }
                        )
            return blockers

        # Phases are evaluated in dependency order; validation guarantees the graph is acyclic.
        remaining = list(phases)
        while remaining:
            progressed = False
            for phase in list(remaining):
                prerequisites = phase_dependencies(phase["id"])["phases"]
                if all(reference in phase_complete for reference in prerequisites):
                    phase_complete[phase["id"]] = compute_phase_complete(phase["id"])
                    remaining.remove(phase)
                    progressed = True
            if not progressed:  # pragma: no cover - defensive, validation rejects cycles
                for phase in remaining:
                    phase_complete[phase["id"]] = compute_phase_complete(phase["id"])
                break

        downstream = _downstream_phase_numbers(phases, items_by_phase, dependencies)

        phase_views: list[dict[str, Any]] = []
        for phase in phases:
            dependencies_of_phase = phase_dependencies(phase["id"])
            entry_blockers = blockers_for(
                dependencies_of_phase["phases"],
                dependencies_of_phase["tickets"],
                include_gates_of=phase["id"],
            )
            entered = not entry_blockers
            phase_entered[phase["id"]] = entered
            entries = items_by_phase.get(phase["id"], [])
            complete = compute_phase_complete(phase["id"])
            if complete:
                state = "complete"
            elif entered:
                state = "active"
            else:
                state = "pending"
            ticket_views: list[dict[str, Any]] = []
            for item in entries:
                explicit = item_dependencies(item["id"])
                blockers = blockers_for(
                    explicit["phases"], explicit["tickets"], include_gates_of=None
                )
                if item["execution_mode"] == "normal" and not entered:
                    blockers.extend(
                        [
                            blocker
                            for blocker in entry_blockers
                            if blocker not in blockers
                        ]
                    )
                human_required = (
                    item["required_actor"] == "human" and item["completed_at"] is None
                )
                ticket_views.append(
                    {
                        "id": item["id"],
                        "key": item["key"],
                        "title": item["title"],
                        "phase_id": item["phase_id"],
                        "phase_number": item["phase_number"],
                        "objective": item["objective"],
                        "instructions": item["instructions"],
                        "required_actor": item["required_actor"],
                        "execution_mode": item["execution_mode"],
                        "acceptance_criteria": json.loads(item["acceptance_criteria_json"] or "[]"),
                        "expected_evidence": json.loads(item["expected_evidence_json"] or "[]"),
                        "human_action_reason": item["human_action_reason"],
                        "human_instructions": item["human_instructions"],
                        "prerequisite_ticket_ids": explicit["tickets"],
                        "prerequisite_phase_ids": explicit["phases"],
                        "card_id": item.get("card_id"),
                        "completed_at": item.get("completed_at"),
                        "ready": not blockers,
                        "blockers": blockers,
                        "human_action_required": human_required,
                        "downstream_phase_numbers": sorted(
                            downstream.get(f"ticket:{item['id']}", set())
                        ),
                    }
                )
            phase_views.append(
                {
                    "id": phase["id"],
                    "number": phase["number"],
                    "name": phase["name"],
                    "objective": phase["objective"],
                    "entry_conditions": json.loads(phase["entry_conditions_json"] or "[]"),
                    "exit_conditions": json.loads(phase["exit_conditions_json"] or "[]"),
                    "prerequisite_phase_ids": dependencies_of_phase["phases"],
                    "prerequisite_ticket_ids": dependencies_of_phase["tickets"],
                    "state": state,
                    "blocked_by": entry_blockers,
                    "tickets": ticket_views,
                }
            )
        if items_by_phase and not any(items_by_phase.values()):
            warnings.append(
                {"code": "plan_empty", "message": "The active plan has no planned Tickets"}
            )
        del loop_id
        return {"phases": phase_views, "warnings": warnings}

    def readiness_item(
        self, conn: Any, loop_row: dict[str, Any], card_id: str
    ) -> dict[str, Any] | None:
        for item in self.readiness(conn, loop_row)["items"]:
            if item.get("card_id") == card_id:
                return item
        return None

    # --- replanning ------------------------------------------------------------

    def change_preview(self, conn: Any, loop_row: dict[str, Any], plan_id: str) -> dict[str, Any]:
        """Compare a candidate plan against the active one before it can be approved."""
        loop_id = loop_row["id"]
        candidate = one(conn, "SELECT * FROM loop_plans WHERE id = :id", {"id": plan_id})
        if candidate is None:
            raise NotFound("Plan not found")
        active = self.active_plan(conn, loop_id)
        new_items = {
            row["id"]: row
            for row in rows(
                conn,
                "SELECT * FROM loop_plan_items WHERE loop_id = :id AND plan_id = :plan",
                {"id": loop_id, "plan": plan_id},
            )
        }
        old_items = (
            {
                row["id"]: row
                for row in rows(
                    conn,
                    "SELECT * FROM loop_plan_items WHERE loop_id = :id AND plan_id = :plan",
                    {"id": loop_id, "plan": active["id"]},
                )
            }
            if active
            else {}
        )
        added, changed, retained, superseded = [], [], [], []
        for item_id, item in new_items.items():
            previous = old_items.get(item_id)
            entry = {"id": item_id, "key": item["key"], "title": item["title"]}
            if previous is None:
                added.append(entry)
            elif (
                previous["title"] != item["title"]
                or previous["instructions"] != item["instructions"]
                or previous["phase_id"] != item["phase_id"]
            ):
                changed.append(entry)
            else:
                retained.append(entry)
        revalidation: list[dict[str, Any]] = []
        for item_id, item in old_items.items():
            if item_id in new_items:
                continue
            card = one(conn, "SELECT * FROM cards WHERE plan_item_id = :id", {"id": item_id})
            superseded.append({"id": item_id, "key": item["key"], "title": item["title"]})
            if card is not None and card["completed_at"] is not None:
                revalidation.append(
                    {
                        "id": item_id,
                        "key": item["key"],
                        "title": item["title"],
                        "reason": "completed_work_excluded",
                    }
                )
        return {
            "added": added,
            "changed": changed,
            "retained": retained,
            "superseded": superseded,
            "revalidation_required": revalidation,
        }

def _downstream_phase_numbers(
    phases: list[dict[str, Any]],
    items_by_phase: dict[str, list[dict[str, Any]]],
    dependencies: dict[str, dict[str, list[str]]],
) -> dict[str, set[int]]:
    """Phase numbers whose entry depends, directly or transitively, on a node."""
    phase_numbers = {phase["id"]: phase["number"] for phase in phases}
    edges: dict[str, set[str]] = {}
    for phase in phases:
        node = f"phase:{phase['id']}"
        edges.setdefault(node, set())
        entry = dependencies.get(node, {"phases": [], "tickets": []})
        edges[node].update(f"phase:{reference}" for reference in entry["phases"])
        edges[node].update(f"ticket:{reference}" for reference in entry["tickets"])
    for phase_id, items in items_by_phase.items():
        for item in items:
            node = f"ticket:{item['id']}"
            edges.setdefault(node, set())
            entry = dependencies.get(node, {"phases": [], "tickets": []})
            edges[node].update(f"ticket:{reference}" for reference in entry["tickets"])
            edges[node].update(f"phase:{reference}" for reference in entry["phases"])
            if item["execution_mode"] == "normal":
                edges[node].add(f"phase:{phase_id}")
    dependents: dict[str, set[str]] = {node: set() for node in edges}
    for node, prerequisites in edges.items():
        for prerequisite in prerequisites:
            dependents.setdefault(prerequisite, set()).add(node)
    result: dict[str, set[int]] = {}
    for node in edges:
        seen: set[str] = set()
        stack = [node]
        numbers: set[int] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            kind, _, identifier = current.partition(":")
            if kind == "phase" and current != node and identifier in phase_numbers:
                numbers.add(phase_numbers[identifier])
            stack.extend(dependents.get(current, ()))
        result[node] = numbers
    return result
