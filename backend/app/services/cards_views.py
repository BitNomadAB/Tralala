"""A Ticket as the API returns it: its row, its board-wide listing and the bulk answer.

The shapes and the functions that build them are pure: ``CardService`` reads the rows, labels,
counts and readiness through the board repositories and hands them here.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from pydantic import JsonValue

from ..db.generated.board import CardsRow, LabelsRow
from ..repositories.cards import CardCounts, CardSort
from .plan_views import Blocker, ReadinessItem
from .subresources import ChecklistEntry, CommentEntry, LabelEntry, label_entries


class CardRecord(TypedDict):
    """A card's row as the API returns it."""

    id: str
    list_id: str
    title: str
    description: str
    position: int
    priority: str
    due_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    version: int
    assignee_actor_id: str | None
    assignee_type: str | None
    assignee_name: str | None
    assigned_at: str | None
    assigned_by_actor_id: str | None
    loop_id: str
    phase_id: str | None
    plan_item_id: str | None
    ticket_key: str | None
    kind: str
    required_actor: str
    execution_mode: str
    human_action_reason: str
    human_instructions: str
    human_confirmed_at: str | None
    human_confirmed_by_actor_id: str | None
    plan_revision_id: str | None


class CardEntry(CardRecord):
    """A Ticket as the API returns it: its row, labels and counts, and its readiness."""

    board_id: str
    labels: list[LabelEntry]
    checklist_total: int
    checklist_completed: int
    comment_count: int
    human_action_required: bool
    ready: bool
    blockers: list[Blocker]
    downstream_phase_numbers: list[int]
    acceptance_criteria: JsonValue
    expected_evidence: JsonValue
    phase_number: int | None
    # The card route adds these when the request asks for them (``?include=``).
    checklists: NotRequired[list[ChecklistEntry]]
    comments: NotRequired[list[CommentEntry]]


class BoardTicketEntry(CardRecord):
    """A Ticket in the board-wide list: its row, its Loop, its labels and counts."""

    loop_key: str
    loop_name: str
    loop_stage: str
    board_id: str
    labels: list[LabelEntry]
    checklist_total: int
    checklist_completed: int
    comment_count: int


class BulkFailure(TypedDict):
    index: int
    code: str
    message: str


class BulkResult(TypedDict):
    created: list[CardEntry]
    failed: list[BulkFailure]


def card_record(row: CardsRow) -> CardRecord:
    return {
        "id": row.id,
        "list_id": row.list_id,
        "title": row.title,
        "description": row.description,
        "position": row.position,
        "priority": row.priority,
        "due_at": row.due_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "archived_at": row.archived_at,
        "version": row.version,
        "assignee_actor_id": row.assignee_actor_id,
        "assignee_type": row.assignee_type,
        "assignee_name": row.assignee_name,
        "assigned_at": row.assigned_at,
        "assigned_by_actor_id": row.assigned_by_actor_id,
        "loop_id": row.loop_id,
        "phase_id": row.phase_id,
        "plan_item_id": row.plan_item_id,
        "ticket_key": row.ticket_key,
        "kind": row.kind,
        "required_actor": row.required_actor,
        "execution_mode": row.execution_mode,
        "human_action_reason": row.human_action_reason,
        "human_instructions": row.human_instructions,
        "human_confirmed_at": row.human_confirmed_at,
        "human_confirmed_by_actor_id": row.human_confirmed_by_actor_id,
        "plan_revision_id": row.plan_revision_id,
    }


def card_entry(
    board_id: str,
    row: CardsRow,
    labels: list[LabelsRow],
    counts: CardCounts,
    item: ReadinessItem | None,
) -> CardEntry:
    """A Ticket's JSON; ``item`` is its planned Ticket's readiness, if the plan has one."""
    if item is not None:
        human_action_required = bool(item["human_action_required"])
    else:
        human_action_required = row.required_actor == "human" and row.completed_at is None
    return {
        **card_record(row),
        "board_id": board_id,
        "labels": label_entries(labels),
        "checklist_total": counts.checklist_total,
        "checklist_completed": counts.checklist_completed,
        "comment_count": counts.comment_count,
        "human_action_required": human_action_required,
        "ready": bool(item["ready"]) if item is not None else True,
        "blockers": item["blockers"] if item is not None else [],
        "downstream_phase_numbers": item["downstream_phase_numbers"] if item is not None else [],
        "acceptance_criteria": item["acceptance_criteria"] if item is not None else [],
        "expected_evidence": item["expected_evidence"] if item is not None else [],
        "phase_number": item["phase_number"] if item is not None else None,
    }


def card_sort(sort: str) -> CardSort:
    """A sort column the list knows; anything else sorts by position."""
    match sort:
        case "created_at" | "updated_at" | "due_at" | "title":
            return sort
        case _:
            return "position"
