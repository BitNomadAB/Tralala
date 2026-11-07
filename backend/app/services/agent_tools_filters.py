"""The filters of ``list_tickets``: what a call was asked to keep, each refused by name when it is
malformed. ``agent_tools_listing`` applies them and re-exports every name here.

A Ticket's ``state`` is ready, needs input or blocked (``ticket_state``); its ``workplace`` says
where the work is done and its ``waiting_for`` what it waits for. Two lists a person asks for are
filters: work that can be taken in a coding session (``workplace`` codebase, ``state`` ready,
``human_action_required`` false), and what needs a person (``needs_person`` true: needs input, or
ready and a person's task).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, get_args

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.errors import ValidationFailure
from ..schemas.cards import WAITING_FOR, WORKPLACES
from ..schemas.common import Priority
from .agent_tools_read import ToolArguments, ToolResult, _text, _whole_number
from .ticket_state import TICKET_STATES

if TYPE_CHECKING:  # the composition root imports this module lazily, so keep the cycle out
    from .cards import CardEntry
    from .lists import ListEntry

SUMMARY_STATES: Final = ("missing", "stale")
PRIORITIES: Final[tuple[str, ...]] = get_args(Priority)


def _flag(args: ToolArguments, key: str) -> bool | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValidationFailure(f"{key} must be true or false", details={"argument": key})
    return value


def choice(args: ToolArguments, key: str, choices: tuple[str, ...]) -> str | None:
    value = _text(args.get(key))
    if value is not None and value not in choices:
        raise ValidationFailure(
            f"{key} must be one of {', '.join(choices)}",
            details={"argument": key, "choices": list(choices)},
        )
    return value


def _names(args: ToolArguments, key: str) -> tuple[str, ...]:
    """A list of texts, or one text; blank entries are dropped."""
    value = args.get(key)
    if value is None:
        return ()
    entries: list[JsonValue] = (
        [value] if isinstance(value, str) else value if isinstance(value, list) else [None]
    )
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            raise ValidationFailure(f"{key} must be a list of texts", details={"argument": key})
        if entry.strip():
            names.append(entry.strip())
    return tuple(names)


def _choices(args: ToolArguments, key: str, choices: tuple[str, ...]) -> tuple[str, ...]:
    """One choice or a list of them, each one of ``choices``."""
    names = _names(args, key)
    wrong = [name for name in names if name not in choices]
    if wrong:
        raise ValidationFailure(
            f"{key} must be one or more of {', '.join(choices)}",
            details={"argument": key, "choices": list(choices)},
        )
    return names


@dataclass(frozen=True, slots=True)
class TicketFilters:
    """What ``list_tickets`` was asked to keep. The card list filters words, owner, label,
    priority, due date and completion itself (``CardService.list``); the column, the Phase, the
    state, the workplace, the wait, who must do it and the summary are applied here, to the Loop's
    Tickets as read."""

    query: str | None = None
    columns: tuple[str, ...] = ()
    assignee: str | None = None
    phase: int | None = None
    states: tuple[str, ...] = ()
    workplace: str | None = None
    waiting_for: str | None = None
    needs_person: bool | None = None
    human: bool | None = None
    label: str | None = None
    priority: str | None = None
    due_before: str | None = None
    overdue: bool = False
    summary: str | None = None
    include_completed: bool = False

    def keeps(self, card: CardEntry) -> bool:
        return all(
            (
                self.phase is None or card["phase_number"] == self.phase,
                not self.states or card["state"] in self.states,
                self.workplace is None or card["workplace"] == self.workplace,
                self.waiting_for is None or card["waiting_for"] == self.waiting_for,
                self.needs_person is None or card["needs_person"] is self.needs_person,
                self.human is None or card["human_action_required"] is self.human,
                self.summary != "missing" or not card["summary"],
                self.summary != "stale" or card["summary_stale"],
            )
        )

    def echo(self) -> ToolResult:
        """The filters as given, so an answer says what it was narrowed by."""
        given: ToolResult = {
            "query": self.query,
            "column": list(self.columns) or None,
            "assignee": self.assignee,
            "phase": self.phase,
            "state": list(self.states) or None,
            "workplace": self.workplace,
            "waiting_for": self.waiting_for,
            "needs_person": self.needs_person,
            "human_action_required": self.human,
            "label": self.label,
            "priority": self.priority,
            "due_before": self.due_before,
            "overdue": self.overdue or None,
            "summary": self.summary,
            "include_completed": self.include_completed or None,
        }
        return {key: value for key, value in given.items() if value is not None}


def ticket_filters(args: ToolArguments) -> TicketFilters:
    """The filters of a ``list_tickets`` call, each refused by name when it is malformed."""
    if "ready" in args:
        raise ValidationFailure(
            "ready is no filter: ask for state ready (or needs_input, blocked)",
            details={"argument": "ready", "use": "state", "choices": list(TICKET_STATES)},
        )
    return TicketFilters(
        query=_text(args.get("query")),
        columns=_names(args, "column"),
        assignee=_text(args.get("assignee")),
        phase=None
        if args.get("phase") is None
        else _whole_number(args, "phase", default=1, maximum=999),
        states=_choices(args, "state", TICKET_STATES),
        workplace=choice(args, "workplace", WORKPLACES),
        waiting_for=choice(args, "waiting_for", WAITING_FOR),
        needs_person=_flag(args, "needs_person"),
        human=_flag(args, "human_action_required"),
        label=_text(args.get("label")),
        priority=choice(args, "priority", PRIORITIES),
        due_before=_text(args.get("due_before")),
        overdue=_flag(args, "overdue") or False,
        summary=choice(args, "summary", SUMMARY_STATES),
        include_completed=_flag(args, "include_completed") or False,
    )


def assignee_filter(assignee: str | None, actor: ActorContext) -> str | None:
    """``me`` is the key's own actor and ``none`` a Ticket nobody has; anything else is an id."""
    if assignee is None:
        return None
    word = assignee.casefold()
    if word == "me":
        return actor.actor_id
    return "unassigned" if word == "none" else assignee


def chosen_columns(columns: list[ListEntry], names: tuple[str, ...]) -> set[str]:
    """The ids of a Loop's columns named by their name (in any case) or by their id."""
    wanted = {name.casefold() for name in names}
    return {
        entry["id"]
        for entry in columns
        if entry["name"].casefold() in wanted or entry["id"] in names
    }


__all__ = [
    "PRIORITIES",
    "SUMMARY_STATES",
    "TicketFilters",
    "assignee_filter",
    "choice",
    "chosen_columns",
    "ticket_filters",
]
