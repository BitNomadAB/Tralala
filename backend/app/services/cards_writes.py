"""Writing a Ticket: inserting one, applying an edit, and the helpers every card write shares.

``CardService`` checks the actor, the board, the Loop, the version and the guards, then hands the
open board repositories here with its id source and its clock, so a write takes ids and timestamps
in the order it always did and runs in a unit test without a database.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..core.context import ActorContext
from ..core.errors import Conflict, Forbidden, NotFound, ValidationFailure, VersionConflict
from ..db.generated.board import CardsRow, LabelsRow, LoopsRow
from ..repositories.board import BoardRepositories
from ..repositories.cards import CardChanges
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.cards import CardCreate, CardUpdate, FaceFields
from .activity import activity_entry
from .loop_identifiers import format_unplanned_key, next_unplanned_sequence
from .loops import refresh_stage
from .ordering import place
from .ticket_face import (
    TicketFace,
    face_findings,
    face_from_text,
    face_missing,
    face_to_text,
    make_face,
    refuse_face,
)
from .ticket_summaries import summary_basis, summary_source

NEW_LABEL_COLOR = "#64748b"
SYSTEM_ACTOR = ActorContext(actor_id="system", actor_type="system", actor_name="Tralala")


@dataclass(frozen=True, slots=True, kw_only=True)
class Assignee:
    actor_id: str
    type: str
    name: str


# --- shared ------------------------------------------------------------------------------------


def ticket_in_loop(repos: BoardRepositories, loop_id: str, card_id: str) -> CardsRow:
    """The Ticket, or ``404``; a Ticket of another Loop is ``409 loop_mismatch``."""
    row = repos.cards.get(card_id)
    if row is None:
        raise NotFound("Card not found")
    if row.loop_id != loop_id:
        raise Conflict(
            "The Ticket belongs to another Loop",
            code="loop_mismatch",
            details={"loop_id": loop_id, "ticket_loop_id": row.loop_id},
        )
    return row


def require_writable(loop: LoopsRow) -> None:
    """A completed, archived or cancelled Loop is read-only: ``409 loop_read_only``."""
    if loop.completed_at is not None or loop.stage == "completed":
        raise Conflict(
            "This Loop is completed and read-only",
            code="loop_read_only",
            details={"loop_id": loop.id},
        )
    if loop.archived_at is not None or loop.cancelled_at is not None:
        raise Conflict(
            "This Loop is not editable", code="loop_read_only", details={"loop_id": loop.id}
        )


def check_version(card: CardsRow, expected: int) -> None:
    """Every card mutation is version-checked: ``409 version_conflict`` on a mismatch."""
    if card.version != expected:
        raise VersionConflict(
            "Card was modified by another actor",
            details={"expected_version": expected, "current_version": card.version},
        )


def card_position(
    repos: BoardRepositories,
    list_id: str,
    index: int | None,
    *,
    exclude: str | None = None,
) -> int:
    placement = place(repos.cards.positions(list_id, exclude=exclude), index)
    if placement.renumbered:
        repos.cards.renumber(placement.renumbered)
    return placement.position


def log_card(
    repos: BoardRepositories,
    actor: ActorContext,
    action: str,
    card_id: str,
    changes: Mapping[str, object] | None = None,
    *,
    new_id: Callable[[], str],
    now: Callable[[], str],
) -> None:
    repos.activity.add(
        activity_entry(
            actor,
            action=action,
            entity_type="card",
            entity_id=card_id,
            changes=changes,
            entry_id=new_id(),
            timestamp=now(),
        )
    )


def label_ids(
    repos: BoardRepositories, references: Sequence[str], *, new_id: Callable[[], str]
) -> list[str]:
    """Labels may be referenced by id or by name; unknown names are created."""
    resolved: list[str] = []
    for raw in references:
        reference = raw.strip()
        if not reference:
            continue
        found = repos.labels.find(reference)
        if found is None:
            label_id = new_id()
            repos.labels.add(LabelsRow(id=label_id, name=reference, color=NEW_LABEL_COLOR))
        else:
            label_id = found.id
        if label_id not in resolved:
            resolved.append(label_id)
    return resolved


def known_label_ids(
    repos: BoardRepositories, names: Sequence[str], *, drop_unknown: bool = False
) -> list[str]:
    """The ids of the board's labels ``names`` name (by name in any case, or by id). An unknown
    one is refused with the names the board has, or left out with ``drop_unknown``; a describer
    (a RoadMap, a worker's follow-up) never invents an area."""
    board = repos.labels.all()
    by_name = {label.name.casefold(): label.id for label in board}
    ids = {label.id for label in board}
    resolved: list[str] = []
    unknown: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        label_id = name if name in ids else by_name.get(name.casefold())
        if label_id is None:
            unknown.append(name)
        elif label_id not in resolved:
            resolved.append(label_id)
    if unknown and not drop_unknown:
        raise ValidationFailure(
            "Unknown label: " + ", ".join(unknown),
            details={"unknown": unknown, "labels": [label.name for label in board]},
        )
    return resolved


# --- the face for people ------------------------------------------------------------------------

FACE_EDIT_REFUSAL = (
    "A Ticket's face for people is changed by a person; a token changes it through a new RoadMap "
    "revision"
)


def _given_face(fields: FaceFields, current: TicketFace) -> TicketFace:
    """``current`` with every face field the request gives in place of its own."""
    return make_face(
        current["why"] if fields.why is None else fields.why,
        current["if_skipped"] if fields.if_skipped is None else fields.if_skipped,
        current["pros"] if fields.pros is None else fields.pros,
        current["cons"] if fields.cons is None else fields.cons,
        current["steps"] if fields.steps is None else fields.steps,
    )


def checked_face(label: str, summary: str, face: TicketFace) -> str:
    """The face as its column stores it, held whole to its template (``422 face_invalid``); a face
    with every field empty is no face and passes."""
    texts = (face["why"], face["if_skipped"], face["pros"], face["cons"], face["steps"])
    if not face_missing("", *texts):
        refuse_face(
            face_findings(
                label,
                summary,
                face["why"],
                face["if_skipped"],
                face["pros"],
                face["cons"],
                face["steps"],
            )
        )
    return face_to_text(face)


def _face_changes(
    actor: ActorContext,
    existing: CardsRow,
    payload: CardUpdate,
    changes: CardChanges,
    logged: dict[str, object],
) -> None:
    """A person's edit of the face, checked whole with the summary the edit leaves; a token's is
    ``403 human_action_required`` (it changes a face through a new RoadMap revision)."""
    if not payload.face_given():
        return
    if not actor.is_user:
        raise Forbidden(
            FACE_EDIT_REFUSAL,
            code="human_action_required",
            details={"action": "edit_face", "actor_type": actor.actor_type},
        )
    current = face_from_text(existing.face) or make_face()
    summary = existing.summary if payload.summary is None else payload.summary
    label = existing.ticket_key or f'"{existing.title}"'
    face = checked_face(label, summary, _given_face(payload, current))
    if face != existing.face:
        changes["face"] = face
        logged["face"] = {"changed": True, "removed": face == ""}


# --- creating ----------------------------------------------------------------------------------


def _summary_changes(
    actor: ActorContext,
    existing: CardsRow,
    summary: str,
    changes: CardChanges,
    logged: dict[str, object],
) -> None:
    """Write ``summary`` as the actor's, from the title and description the edit leaves; an empty
    one removes it. The same text written again over a changed Ticket confirms it (fresh basis)."""
    title = changes.get("title", existing.title)
    description = changes.get("description", existing.description)
    wanted = ("", "", "")
    if summary:
        wanted = (summary, summary_source(actor), summary_basis(title, description))
    current = (existing.summary, existing.summary_source, existing.summary_basis_sha256)
    if wanted == current:
        return
    changes["summary"], changes["summary_source"], changes["summary_basis_sha256"] = wanted
    logged["summary"] = {"changed": True, "source": wanted[1]}


def insert_card(
    repos: BoardRepositories,
    actor: ActorContext,
    loop: LoopsRow,
    payload: CardCreate,
    *,
    new_id: Callable[[], str],
    now: Callable[[], str],
    known_labels_only: bool = False,
) -> CardsRow:
    """Insert the Ticket ``payload`` describes; its labels are created when the board lacks them,
    or, with ``known_labels_only``, refused with the names the board has."""
    list_id = payload.list_id
    labels = known_label_ids(repos, payload.labels) if known_labels_only else None
    active = {row.id for row in repos.lists.for_loop(loop.id, include_archived=False)}
    if list_id not in active:
        other = repos.lists.get(list_id)
        if other is not None and other.loop_id != loop.id:
            raise Conflict(
                "The column belongs to another Loop",
                code="loop_mismatch",
                details={"list_id": list_id},
            )
        raise ValidationFailure(
            "List does not exist or is archived", details={"list_id": list_id}
        )
    card_id = new_id()
    timestamp = now()
    # Work added to a Loop that executes a plan is outside it: keyed so a person can follow it.
    key = None
    if loop.current_plan_id:
        sequence = next_unplanned_sequence(
            loop.key, [row.ticket_key for row in repos.cards.manual(loop.id)]
        )
        key = format_unplanned_key(loop.key, sequence)
    face = ""
    if payload.face_given():
        label = key or f'"{payload.title}"'
        face = checked_face(label, payload.summary, _given_face(payload, make_face()))
    repos.cards.add(
        CardsRow(
            id=card_id,
            list_id=list_id,
            title=payload.title,
            description=payload.description,
            position=card_position(repos, list_id, None),
            priority=payload.priority,
            due_at=payload.due_at,
            completed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
            archived_at=None,
            version=1,
            assignee_actor_id=None,
            assignee_type=None,
            assignee_name=None,
            assigned_at=None,
            assigned_by_actor_id=None,
            loop_id=loop.id,
            phase_id=None,
            plan_item_id=None,
            ticket_key=key,
            kind="manual",
            required_actor="any",
            execution_mode="normal",
            human_action_reason="",
            human_instructions="",
            human_confirmed_at=None,
            human_confirmed_by_actor_id=None,
            plan_revision_id=None,
            summary=payload.summary,
            summary_source=summary_source(actor) if payload.summary else "",
            summary_basis_sha256=(
                summary_basis(payload.title, payload.description) if payload.summary else ""
            ),
            workplace=payload.workplace,
            waiting_for=payload.waiting_for,
            waiting_reason=payload.waiting_reason,
            waiting_set_at=None if payload.waiting_for == "nothing" else timestamp,
            waiting_set_by=None if payload.waiting_for == "nothing" else actor.actor_id,
            face=face,
        )
    )
    if labels is None and payload.labels:
        labels = label_ids(repos, payload.labels, new_id=new_id)
    if labels:
        repos.cards.set_labels(card_id, labels)
    row = ticket_in_loop(repos, loop.id, card_id)
    log_card(
        repos,
        actor,
        "card.created",
        card_id,
        {
            "title": payload.title,
            "list_id": list_id,
            "loop_id": loop.id,
            **({} if payload.workplace == "unknown" else {"workplace": payload.workplace}),
            **({} if payload.waiting_for == "nothing" else {"waiting_for": payload.waiting_for}),
            **({"face": True} if face else {}),
        },
        new_id=new_id,
        now=now,
    )
    return row


# --- editing -----------------------------------------------------------------------------------


def resolve_assignee(accounts: RegistryUnitOfWork, assignee_id: str) -> Assignee:
    """Validate a human actor or an enabled registry agent as the primary assignee."""
    with accounts.reader() as registry:
        person = registry.actors.enabled(assignee_id)
        agent = None if person is not None else registry.agents.get(assignee_id)
    if person is not None:
        return Assignee(actor_id=person.id, type=person.type, name=person.name)
    if agent is None:
        raise ValidationFailure(
            "Assignee must be a human user or a registered agent",
            details={"assignee_actor_id": assignee_id},
        )
    if not agent.enabled:
        raise ValidationFailure(
            "Agent is disabled and cannot be assigned",
            details={"assignee_actor_id": assignee_id},
        )
    return Assignee(actor_id=agent.id, type="agent", name=agent.name)


def invalidate_after_reopen(
    repos: BoardRepositories,
    loop: LoopsRow,
    card: CardsRow,
    *,
    new_id: Callable[[], str],
    now: Callable[[], str],
) -> None:
    """Reopening a prerequisite invalidates QA evidence prepared against the old baseline."""
    timestamp = now()
    repos.qa.supersede_open(loop.id, now=timestamp)
    repos.loops.clear_delivery_approvals(loop.id, now=timestamp)
    log_card(
        repos,
        SYSTEM_ACTOR,
        "loop.reopened_work",
        card.id,
        {"revalidation_required": True},
        new_id=new_id,
        now=now,
    )


def apply_update(
    repos: BoardRepositories,
    actor: ActorContext,
    loop: LoopsRow,
    existing: CardsRow,
    payload: CardUpdate,
    *,
    accounts: RegistryUnitOfWork,
    new_id: Callable[[], str],
    now: Callable[[], str],
) -> None:
    """Write the fields ``payload`` changes, log them and refresh the Loop's stage on completion.

    The caller has checked the Loop, the version and the guards; ``existing`` is the Ticket as it
    read it in the same unit of work.
    """
    card_id = existing.id
    logged: dict[str, object] = {}
    changes: CardChanges = {}
    # First, so a refused face writes nothing.
    _face_changes(actor, existing, payload, changes, logged)
    if payload.title is not None and payload.title != existing.title:
        changes["title"] = payload.title
        logged["title"] = {"before": existing.title, "after": payload.title}
    if payload.description is not None and payload.description != existing.description:
        changes["description"] = payload.description
        logged["description"] = {"changed": True}
    if payload.priority is not None and payload.priority != existing.priority:
        changes["priority"] = payload.priority
        logged["priority"] = {"before": existing.priority, "after": payload.priority}
    if payload.clear_due_at:
        changes["due_at"] = None
        logged["due_at"] = {"before": existing.due_at, "after": None}
    elif payload.due_at is not None and payload.due_at != existing.due_at:
        changes["due_at"] = payload.due_at
        logged["due_at"] = {"before": existing.due_at, "after": payload.due_at}
    if payload.completed is not None:
        already = existing.completed_at is not None
        if payload.completed and not already:
            changes["completed_at"] = now()
            logged["completed"] = {"before": False, "after": True}
            if existing.required_actor == "human":
                changes["human_confirmed_at"] = now()
                changes["human_confirmed_by_actor_id"] = actor.actor_id
                logged["human_confirmation"] = {"actor_id": actor.actor_id}
        elif not payload.completed and already:
            changes["completed_at"] = None
            changes["human_confirmed_at"] = None
            changes["human_confirmed_by_actor_id"] = None
            logged["completed"] = {"before": True, "after": False}
            invalidate_after_reopen(repos, loop, existing, new_id=new_id, now=now)
    if payload.labels is not None:
        repos.cards.set_labels(card_id, label_ids(repos, payload.labels, new_id=new_id))
        logged["labels"] = {"after": payload.labels}
    if payload.clear_assignee:
        changes["assignee_actor_id"] = None
        changes["assignee_type"] = None
        changes["assignee_name"] = None
        changes["assigned_at"] = None
        changes["assigned_by_actor_id"] = None
        logged["assignee"] = {"before": existing.assignee_actor_id, "after": None}
    elif payload.assignee_actor_id is not None:
        assignee = resolve_assignee(accounts, payload.assignee_actor_id)
        if assignee.actor_id != existing.assignee_actor_id:
            changes["assignee_actor_id"] = assignee.actor_id
            changes["assignee_type"] = assignee.type
            changes["assignee_name"] = assignee.name
            changes["assigned_at"] = now()
            changes["assigned_by_actor_id"] = actor.actor_id
            logged["assignee"] = {
                "before": existing.assignee_actor_id,
                "after": assignee.actor_id,
                "name": assignee.name,
                "type": assignee.type,
            }
    if payload.summary is not None:
        _summary_changes(actor, existing, payload.summary, changes, logged)
    if changes:
        changes["version"] = existing.version + 1
        changes["updated_at"] = now()
        repos.cards.update(card_id, changes)
    if logged:
        log_card(repos, actor, "card.updated", card_id, logged, new_id=new_id, now=now)
    if "completed" in logged:
        refresh_stage(repos, loop.id, now=now())
