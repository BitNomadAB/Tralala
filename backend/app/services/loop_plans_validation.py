"""A RoadMap's validation before anything is stored: UUID identities, unique Phase numbers,
references that resolve, human-only Tickets that say why and how, and a dependency graph without
cycles. ``loop_plans`` re-exports ``validate_plan``, so callers keep importing it from there.
"""

from __future__ import annotations

import uuid

from ..core.errors import ValidationFailure
from ..schemas.loops import PlanPayload, PlanTicket

# --- validation ----------------------------------------------------------------------------------


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (TypeError, ValueError):
        return False
    return True


def validate_plan(payload: PlanPayload) -> None:
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
            _validate_ticket(ticket, phase_ids, ticket_ids)

    _reject_cycles(payload, tickets, phase_of_ticket)


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
    if ticket.required_actor == "human" and (
        not ticket.human_action_reason.strip() or not ticket.human_instructions.strip()
    ):
        raise ValidationFailure(
            "A human-only Ticket needs a reason and instructions",
            code="invalid_dependency_graph",
            details={"ticket_id": ticket.id},
        )


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
                details={"cycle": [*path, node]},
            )
        if state.get(node) == 2:
            return
        state[node] = 1
        for target in sorted(graph.get(node, ())):
            visit(target, [*path, node])
        state[node] = 2

    for node in sorted(graph):
        visit(node, [])
