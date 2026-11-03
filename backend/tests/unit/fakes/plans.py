"""The plan views as the Loop and Ticket services read them, without a plan service."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.generated.board import LoopsRow
from app.repositories.board import BoardRepositories
from app.services.plan_views import Blocker, PlanView, PlanViews, Readiness, ReadinessItem


def readiness_item(
    card_id: str | None,
    *,
    ready: bool = True,
    blockers: tuple[Blocker, ...] = (),
    human: bool = False,
    phase_number: int = 1,
) -> ReadinessItem:
    """A planned Ticket's readiness; ``card_id`` is the card that carries it."""
    return {
        "id": f"item-{card_id}",
        "key": f"K-{card_id}",
        "title": f"Item {card_id}",
        "phase_id": "phase-1",
        "phase_number": phase_number,
        "objective": "",
        "instructions": "",
        "required_actor": "human" if human else "any",
        "execution_mode": "normal",
        "acceptance_criteria": ["it works"],
        "expected_evidence": ["a test"],
        "human_action_reason": "",
        "human_instructions": "",
        "prerequisite_ticket_ids": [],
        "prerequisite_phase_ids": [],
        "card_id": card_id,
        "completed_at": None,
        "ready": ready,
        "blockers": list(blockers),
        "human_action_required": human,
        "downstream_phase_numbers": [2],
    }


BLOCKER: Blocker = {
    "type": "ticket",
    "id": "item-first",
    "key": "K-first",
    "title": "First",
    "reason": "prerequisite_ticket_incomplete",
}


@dataclass(slots=True)
class FakePlanViews:
    """Answers with the items a test sets and records which Loop each view was asked for."""

    items: list[ReadinessItem] = field(default_factory=list[ReadinessItem])
    calls: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])

    def plan_view(self, repos: BoardRepositories, loop: LoopsRow) -> PlanView:
        del repos  # the views a test sets do not depend on the board
        self.calls.append(("plan_view", loop.id, loop.stage))
        return {
            "loop_id": loop.id,
            "plan_id": loop.current_plan_id,
            "revision_number": None,
            "status": "none",
            "activated_at": None,
            "approved_at": None,
            "phases": [],
            "warnings": [],
        }

    def readiness(self, repos: BoardRepositories, loop: LoopsRow) -> Readiness:
        del repos
        self.calls.append(("readiness", loop.id, loop.stage))
        return {
            "loop_id": loop.id,
            "stage": loop.stage,
            "execution_allowed": True,
            "blocked_reason": None,
            "items": list(self.items),
            "phases": [],
        }


def plan_views(views: FakePlanViews) -> PlanViews:
    """The fake as the Protocol the services take; pyright proves the contract."""
    return views
