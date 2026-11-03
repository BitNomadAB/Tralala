"""A board's labels and a Ticket's checklists and comments.

Labels belong to the board. Checklists and comments belong to a Ticket and follow its Loop: a
completed, archived or cancelled Loop refuses them with ``409 loop_read_only``
(``loops.ensure_ticket_writable``). The services reach the board database only through the board
unit of work, the registry (who wrote a comment) only through the registry unit of work and the
board's registry row through ``BoardChecks``; the clock and the id source are passed in, so every
rule here runs in a unit test without a database. A comment that mentions someone is handed to
``MentionQueue``, best effort.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, TypedDict
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict, Forbidden, NotFound
from ..db.generated.board import (
    CardsRow,
    ChecklistItemsRow,
    ChecklistsRow,
    CommentsRow,
    LabelsRow,
)
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.checklists import ChecklistItemChanges
from ..repositories.labels import LabelChanges
from ..repositories.registry import RegistryUnitOfWork
from ..schemas.subresources import (
    ChecklistCreate,
    ChecklistItemCreate,
    ChecklistItemUpdate,
    ChecklistUpdate,
    CommentCreate,
    LabelCreate,
    LabelUpdate,
)
from .activity import activity_entry
from .lists import BoardChecks
from .loops import ensure_ticket_writable
from .ordering import place

logger = logging.getLogger(__name__)


class LabelEntry(TypedDict):
    id: str
    name: str
    color: str


class ChecklistItemEntry(TypedDict):
    id: str
    checklist_id: str
    text: str
    completed: bool
    position: int


class ChecklistEntry(TypedDict):
    """A checklist as the API returns it: its row and its items in display order."""

    id: str
    card_id: str
    title: str
    position: int
    items: list[ChecklistItemEntry]


class CommentEntry(TypedDict):
    """A comment as the API returns it: its row and who wrote it (None when nobody is known)."""

    id: str
    card_id: str
    actor_id: str
    content: str
    created_at: str
    updated_at: str
    actor_name: str | None
    actor_type: str | None


class MentionQueue(Protocol):
    """Where a comment that mentions an agent asks for an answer (``MentionService``)."""

    def queue(
        self, actor: ActorContext, board_id: str, card_id: str, comment_id: str, content: str
    ) -> object: ...


def label_entry(row: LabelsRow) -> LabelEntry:
    return {"id": row.id, "name": row.name, "color": row.color}


def label_entries(rows: Sequence[LabelsRow]) -> list[LabelEntry]:
    return [label_entry(row) for row in rows]


def checklist_item_entry(row: ChecklistItemsRow) -> ChecklistItemEntry:
    return {
        "id": row.id,
        "checklist_id": row.checklist_id,
        "text": row.text,
        "completed": bool(row.completed),
        "position": row.position,
    }


def checklist_entries(
    checklists: Sequence[ChecklistsRow], items: Sequence[ChecklistItemsRow]
) -> list[ChecklistEntry]:
    """Each checklist with its own items, both in the order given."""
    return [
        {
            "id": checklist.id,
            "card_id": checklist.card_id,
            "title": checklist.title,
            "position": checklist.position,
            "items": [
                checklist_item_entry(item) for item in items if item.checklist_id == checklist.id
            ],
        }
        for checklist in checklists
    ]


def _position(
    siblings: Sequence[tuple[str, int]],
    index: int | None,
    renumber: Callable[[Sequence[tuple[str, int]]], None],
) -> int:
    """``ordering.place`` among ``siblings``, renumbering them first when it asks for that."""
    placement = place(siblings, index)
    if placement.renumbered:
        renumber(placement.renumbered)
    return placement.position


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class _BoardParts:
    """What the three services share: the board checks, the store, the clock and the id source."""

    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    def _log(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: Mapping[str, object],
    ) -> None:
        repos.activity.add(
            activity_entry(
                actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                changes=changes,
                entry_id=self._new_id(),
                timestamp=self._now(),
            )
        )


def label_name_taken(name: str) -> Conflict:
    """A label name is unique on its board (exactly, as the column's UNIQUE compares it); a create
    or a rename to a taken name answers as every other taken name does."""
    return Conflict(
        "A label with this name already exists", code="label_name_taken", details={"name": name}
    )


class LabelService(_BoardParts):
    def list(self, board_id: str) -> list[LabelEntry]:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return label_entries(repos.labels.all())

    def create(self, actor: ActorContext, board_id: str, payload: LabelCreate) -> LabelEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        row = LabelsRow(id=self._new_id(), name=payload.name, color=payload.color)
        with self.store.writer(board_id) as repos:
            if repos.labels.by_name(payload.name) is not None:
                raise label_name_taken(payload.name)
            repos.labels.add(row)
            self._log(
                repos,
                actor,
                action="label.created",
                entity_type="label",
                entity_id=row.id,
                changes={"name": payload.name, "color": payload.color},
            )
        return label_entry(row)

    def update(
        self, actor: ActorContext, board_id: str, label_id: str, payload: LabelUpdate
    ) -> LabelEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        changes: LabelChanges = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.color is not None:
            changes["color"] = payload.color
        with self.store.writer(board_id) as repos:
            existing = repos.labels.get(label_id)
            if existing is None:
                raise NotFound("Label not found")
            if "name" in changes:
                holder = repos.labels.by_name(changes["name"])
                if holder is not None and holder.id != label_id:
                    raise label_name_taken(changes["name"])
            if changes:
                repos.labels.update(label_id, changes)
                self._log(
                    repos,
                    actor,
                    action="label.updated",
                    entity_type="label",
                    entity_id=label_id,
                    changes={"before": label_entry(existing), "after": changes},
                )
        return label_entry(existing.__replace__(**changes))

    def delete(self, actor: ActorContext, board_id: str, label_id: str) -> None:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            existing = repos.labels.get(label_id)
            if existing is None:
                raise NotFound("Label not found")
            repos.labels.delete(label_id)
            self._log(
                repos,
                actor,
                action="label.deleted",
                entity_type="label",
                entity_id=label_id,
                changes={"name": existing.name},
            )


class ChecklistService(_BoardParts):
    @staticmethod
    def _card(repos: BoardRepositories, card_id: str) -> CardsRow:
        card = repos.cards.get(card_id)
        if card is None:
            raise NotFound("Card not found")
        return card

    @staticmethod
    def _checklist(repos: BoardRepositories, checklist_id: str) -> ChecklistsRow:
        checklist = repos.checklists.get(checklist_id)
        if checklist is None:
            raise NotFound("Checklist not found")
        return checklist

    @staticmethod
    def _item(repos: BoardRepositories, item_id: str) -> ChecklistItemsRow:
        item = repos.checklist_items.get(item_id)
        if item is None:
            raise NotFound("Checklist item not found")
        ChecklistService._ensure_item_writable(repos, item)
        return item

    @staticmethod
    def _ensure_item_writable(repos: BoardRepositories, item: ChecklistItemsRow) -> None:
        checklist = repos.checklists.get(item.checklist_id)
        if checklist is not None:
            ensure_ticket_writable(repos, checklist.card_id)

    def list(self, board_id: str, card_id: str) -> list[ChecklistEntry]:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            self._card(repos, card_id)
            return checklist_entries(
                repos.checklists.for_card(card_id), repos.checklist_items.for_card(card_id)
            )

    def create(
        self, actor: ActorContext, board_id: str, card_id: str, payload: ChecklistCreate
    ) -> ChecklistEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        checklist_id = self._new_id()
        with self.store.writer(board_id) as repos:
            self._card(repos, card_id)
            ensure_ticket_writable(repos, card_id)
            siblings = [(row.id, row.position) for row in repos.checklists.for_card(card_id)]
            row = ChecklistsRow(
                id=checklist_id,
                card_id=card_id,
                title=payload.title,
                position=_position(siblings, None, repos.checklists.renumber),
            )
            repos.checklists.add(row)
            self._log(
                repos,
                actor,
                action="checklist.created",
                entity_type="checklist",
                entity_id=checklist_id,
                changes={"card_id": card_id, "title": payload.title},
            )
        return checklist_entries([row], [])[0]

    def update(
        self, actor: ActorContext, board_id: str, checklist_id: str, payload: ChecklistUpdate
    ) -> ChecklistEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            checklist = self._checklist(repos, checklist_id)
            ensure_ticket_writable(repos, checklist.card_id)
            if payload.title is not None and payload.title != checklist.title:
                repos.checklists.rename(checklist_id, payload.title)
                self._log(
                    repos,
                    actor,
                    action="checklist.updated",
                    entity_type="checklist",
                    entity_id=checklist_id,
                    changes={"before": checklist.title, "after": payload.title},
                )
                checklist = checklist.__replace__(title=payload.title)
            items = repos.checklist_items.for_checklist(checklist_id)
        return checklist_entries([checklist], items)[0]

    def delete(self, actor: ActorContext, board_id: str, checklist_id: str) -> None:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            checklist = self._checklist(repos, checklist_id)
            ensure_ticket_writable(repos, checklist.card_id)
            repos.checklists.delete(checklist_id)
            self._log(
                repos,
                actor,
                action="checklist.deleted",
                entity_type="checklist",
                entity_id=checklist_id,
                changes={"card_id": checklist.card_id},
            )

    def add_item(
        self,
        actor: ActorContext,
        board_id: str,
        checklist_id: str,
        payload: ChecklistItemCreate,
    ) -> ChecklistItemEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        item_id = self._new_id()
        with self.store.writer(board_id) as repos:
            checklist = self._checklist(repos, checklist_id)
            ensure_ticket_writable(repos, checklist.card_id)
            siblings = [
                (item.id, item.position)
                for item in repos.checklist_items.for_checklist(checklist_id)
            ]
            row = ChecklistItemsRow(
                id=item_id,
                checklist_id=checklist_id,
                text=payload.text,
                completed=0,
                position=_position(siblings, payload.position, repos.checklist_items.renumber),
            )
            repos.checklist_items.add(row)
            self._log(
                repos,
                actor,
                action="checklist.item_added",
                entity_type="checklist_item",
                entity_id=item_id,
                changes={"checklist_id": checklist_id, "text": payload.text},
            )
        return checklist_item_entry(row)

    def update_item(
        self,
        actor: ActorContext,
        board_id: str,
        item_id: str,
        payload: ChecklistItemUpdate,
    ) -> ChecklistItemEntry:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            item = self._item(repos, item_id)
            changes: ChecklistItemChanges = {}
            if payload.text is not None:
                changes["text"] = payload.text
            if payload.completed is not None:
                changes["completed"] = 1 if payload.completed else 0
            if payload.position is not None:
                siblings = [
                    (sibling.id, sibling.position)
                    for sibling in repos.checklist_items.for_checklist(item.checklist_id)
                    if sibling.id != item_id
                ]
                changes["position"] = _position(
                    siblings, payload.position, repos.checklist_items.renumber
                )
            if changes:
                repos.checklist_items.update(item_id, changes)
                self._log(
                    repos,
                    actor,
                    action="checklist.item_updated",
                    entity_type="checklist_item",
                    entity_id=item_id,
                    changes=changes,
                )
        return checklist_item_entry(item.__replace__(**changes))

    def delete_item(self, actor: ActorContext, board_id: str, item_id: str) -> None:
        actor.require("cards:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            item = self._item(repos, item_id)
            repos.checklist_items.delete(item_id)
            self._log(
                repos,
                actor,
                action="checklist.item_deleted",
                entity_type="checklist_item",
                entity_id=item_id,
                changes={"checklist_id": item.checklist_id, "text": item.text},
            )


class CommentService(_BoardParts):
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        accounts: RegistryUnitOfWork,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        super().__init__(boards, store, clock=clock, new_id=new_id)
        self.accounts = accounts
        # Set by the composition root once the mention service exists.
        self.mentions: MentionQueue | None = None

    def _decorate(self, comments: Sequence[CommentsRow]) -> list[CommentEntry]:
        """Each comment with its author's name and type: a person or token actor by its actor
        row, otherwise an agent profile of that id; unknown when neither exists."""
        authors = self._authors({comment.actor_id for comment in comments})
        return [
            {
                "id": comment.id,
                "card_id": comment.card_id,
                "actor_id": comment.actor_id,
                "content": comment.content,
                "created_at": comment.created_at,
                "updated_at": comment.updated_at,
                "actor_name": authors.get(comment.actor_id, (None, None))[0],
                "actor_type": authors.get(comment.actor_id, (None, None))[1],
            }
            for comment in comments
        ]

    def _authors(self, actor_ids: Collection[str]) -> dict[str, tuple[str, str]]:
        if not actor_ids:
            return {}
        with self.accounts.reader() as registry:
            actors = registry.actors.many(actor_ids)
            missing = [actor_id for actor_id in actor_ids if actor_id not in actors]
            agents = registry.agents.names(missing) if missing else {}
        found = {actor_id: (actor.name, actor.type) for actor_id, actor in actors.items()}
        found.update((agent_id, (name, "agent")) for agent_id, name in agents.items())
        return found

    @staticmethod
    def _comment(repos: BoardRepositories, actor: ActorContext, comment_id: str) -> CommentsRow:
        """The comment the actor may change: a person any, an agent only its own, and only while
        the Ticket's Loop is writable."""
        comment = repos.comments.get(comment_id)
        if comment is None:
            raise NotFound("Comment not found")
        if not actor.is_user and comment.actor_id != actor.actor_id:
            raise Forbidden("Agents may only modify their own comments")
        ensure_ticket_writable(repos, comment.card_id)
        return comment

    def list(self, board_id: str, card_id: str) -> list[CommentEntry]:
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            comments = repos.comments.for_card(card_id)
        return self._decorate(comments)

    def create(
        self, actor: ActorContext, board_id: str, card_id: str, payload: CommentCreate
    ) -> CommentEntry:
        actor.require("comments:write")
        self.boards.ensure_active(board_id)
        comment_id = self._new_id()
        now = self._now()
        row = CommentsRow(
            id=comment_id,
            card_id=card_id,
            actor_id=actor.actor_id,
            content=payload.content,
            created_at=now,
            updated_at=now,
        )
        with self.store.writer(board_id) as repos:
            if repos.cards.get(card_id) is None:
                raise NotFound("Card not found")
            ensure_ticket_writable(repos, card_id)
            repos.comments.add(row)
            self._log(
                repos,
                actor,
                action="comment.created",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": card_id},
            )
        if self.mentions is not None and "@" in payload.content:
            try:
                self.mentions.queue(actor, board_id, card_id, comment_id, payload.content)
            except Exception:  # the comment is saved; mentions are best effort
                logger.exception("Could not queue mentions for comment %s", comment_id)
        return self._decorate([row])[0]

    def update(
        self, actor: ActorContext, board_id: str, comment_id: str, payload: CommentCreate
    ) -> CommentEntry:
        actor.require("comments:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            comment = self._comment(repos, actor, comment_id)
            now = self._now()
            repos.comments.edit(comment_id, payload.content, now=now)
            self._log(
                repos,
                actor,
                action="comment.updated",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": comment.card_id},
            )
        return self._decorate([comment.__replace__(content=payload.content, updated_at=now)])[0]

    def delete(self, actor: ActorContext, board_id: str, comment_id: str) -> None:
        actor.require("comments:write")
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            comment = self._comment(repos, actor, comment_id)
            repos.comments.delete(comment_id)
            self._log(
                repos,
                actor,
                action="comment.deleted",
                entity_type="comment",
                entity_id=comment_id,
                changes={"card_id": comment.card_id},
            )
