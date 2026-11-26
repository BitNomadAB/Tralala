"""Where a Ticket's work is done and what it waits for: the writes.

``workplace`` describes the work and assigns nothing, so anyone who may edit a Ticket
(``cards:write``) changes it. A wait is what the Ticket needs before work can go on ("I need this
answered"): anyone with ``cards:write`` may set one on a Ticket that waits for nothing, with a
reason. Clearing a wait, or replacing one with another, is a person's act (``403
human_action_required`` for a token, AGENTS.md rule 11a): the person who answers the question
closes it, whether it waited for a decision, information, access or a third party. A wait may name
the line of the Loop's stop list it is for (``stop``, by the line's text or its number,
``loop_stops.match_stop``); the line is stored in ``waiting_stop`` and cleared with the wait, and
a wait that names something not on the list is ``422 not_a_stop``. A wait without a stop works as
it always did.

Every write is version-checked (``409 version_conflict``), refused on a read-only Loop (``409
loop_read_only``) and on a completed Ticket (``409 ticket_completed``), and logged on the card.
Writing what the Ticket already says changes nothing and keeps the version. The state a list shows
is computed from these fields on every read (``ticket_state``).

The service reaches the board only through the board unit of work and answers the Ticket as
``CardService.get`` does; the clock is an argument, so every rule runs in a unit test on the fakes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import Conflict
from ..db.generated.board import CardsRow, LoopsRow
from ..repositories.board import BoardRepositories, BoardUnitOfWork
from ..repositories.cards import CardChanges
from ..schemas.cards import TicketWaitClear, TicketWaitSet, TicketWorkplaceUpdate
from .cards import CardEntry, CardService
from .cards_writes import check_version, log_card, require_writable, ticket_in_loop
from .decision_outcomes import AskedDecision
from .decision_requests import add_answer_comment, open_questions, with_asked_through
from .lists import BoardChecks
from .loop_stops import require_stop
from .loops import require_loop


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class TicketWorkService:
    def __init__(
        self,
        boards: BoardChecks,
        store: BoardUnitOfWork,
        tickets: CardService,
        *,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        self.boards = boards
        self.store = store
        self.tickets = tickets
        self._clock = clock
        self._new_id = new_id

    def _now(self) -> str:
        return iso_utc(self._clock())

    def set_workplace(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: TicketWorkplaceUpdate,
    ) -> CardEntry:
        """Where the work is done: ``codebase``, ``outside`` or ``unknown``."""
        actor.require("cards:write")

        def change(_loop: LoopsRow, card: CardsRow) -> CardChanges:
            return {} if card.workplace == payload.workplace else {"workplace": payload.workplace}

        return self._write(
            actor,
            (board_id, loop_id, card_id),
            payload.version,
            change,
            "card.workplace_changed",
            {"workplace": payload.workplace},
        )

    def set_wait(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: TicketWaitSet,
    ) -> CardEntry:
        """The Ticket waits for ``payload.waiting_for`` because of ``payload.reason``, for the
        stop-list line ``payload.stop`` names when it names one; replacing another wait is a
        person's act."""
        actor.require("cards:write")
        logged: dict[str, object] = {"waiting_for": payload.waiting_for, "reason": payload.reason}

        def change(loop: LoopsRow, card: CardsRow) -> CardChanges:
            stop = require_stop(loop, payload.stop) if payload.stop else None
            if stop is not None:
                logged["stop"] = stop
            # The same wait again changes nothing; one that names no stop keeps the stop the wait
            # has, so a caller that never names one retries as it always did.
            same = (card.waiting_for, card.waiting_reason) == (payload.waiting_for, payload.reason)
            if same and stop in (None, card.waiting_stop):
                return {}
            if card.waiting_for != "nothing":
                actor.require_human("Replacing a Ticket's wait")
            return {
                "waiting_for": payload.waiting_for,
                "waiting_reason": payload.reason,
                "waiting_set_at": self._now(),
                "waiting_set_by": actor.actor_id,
                "waiting_stop": stop,
            }

        return self._write(
            actor, (board_id, loop_id, card_id), payload.version, change, "card.wait_set", logged
        )

    def clear_wait(
        self,
        actor: ActorContext,
        board_id: str,
        loop_id: str,
        card_id: str,
        payload: TicketWaitClear,
    ) -> CardEntry:
        """The wait is answered: a person's act, whatever the Ticket waited for, in Tralala or
        in the editor through a key with the right (AGENTS.md rule 11a)."""
        actor.require_person_or_editor_decision("Clearing a Ticket's wait")
        actor.require("cards:write")

        def change(_loop: LoopsRow, card: CardsRow) -> CardChanges:
            if card.waiting_for == "nothing":
                return {}
            return {
                "waiting_for": "nothing",
                "waiting_reason": "",
                "waiting_set_at": None,
                "waiting_set_by": None,
                "waiting_stop": None,
            }

        return self._write(
            actor,
            (board_id, loop_id, card_id),
            payload.version,
            change,
            "card.wait_cleared",
            {},
            answers="wait",
        )

    def _write(
        self,
        actor: ActorContext,
        address: tuple[str, str, str],
        version: int,
        change: Callable[[LoopsRow, CardsRow], CardChanges],
        action: str,
        logged: Mapping[str, object],
        *,
        answers: AskedDecision | None = None,
    ) -> CardEntry:
        """Write ``change`` (of the Loop and the Ticket as the writer reads them) to the Ticket in
        one writer; ``logged`` is read after ``change`` ran, so it may add to it. A write that
        takes a person's decision (``answers``) answers the questions a coding session has open
        about it: its history row carries ``asked_through`` and the Ticket gets one comment by the
        person, in the same writer (``decision_requests``)."""
        board_id, loop_id, card_id = address
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            require_writable(loop)
            card = ticket_in_loop(repos, loop_id, card_id)
            check_version(card, version)
            if card.completed_at is not None:
                raise Conflict(
                    "This Ticket is completed",
                    code="ticket_completed",
                    details={"ticket_id": card.id, "ticket_key": card.ticket_key},
                )
            changes = change(loop, card)
            if changes:
                now = self._now()
                through = (
                    open_questions(
                        repos, loop_id=loop_id, decision=answers, card_id=card.id, now=now
                    )
                    if answers is not None
                    else []
                )
                marked = with_asked_through(
                    logged, through, actor if answers is not None else None
                )
                self._apply(repos, actor, card, changes, action, marked)
                if answers is not None:
                    add_answer_comment(
                        repos, actor, card.id, answers, through, new_id=self._new_id, now=now
                    )
        return self.tickets.get(board_id, loop_id, card_id)

    def _apply(
        self,
        repos: BoardRepositories,
        actor: ActorContext,
        card: CardsRow,
        changes: CardChanges,
        action: str,
        logged: Mapping[str, object],
    ) -> None:
        before: dict[str, object] = {
            "workplace": card.workplace,
            "waiting_for": card.waiting_for,
        }
        changes["version"] = card.version + 1
        changes["updated_at"] = self._now()
        repos.cards.update(card.id, changes)
        log_card(
            repos,
            actor,
            action,
            card.id,
            {**logged, "before": before},
            new_id=self._new_id,
            now=self._now,
        )


__all__ = ["TicketWorkService"]
