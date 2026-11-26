"""A Loop's stop list: the only things that stop work and wait for a person.

An obstacle in a Loop is one of three kinds. A choice that can be changed afterwards is a POC
decision, and something missing from a person is reported as missing (``poc_decisions``); neither
stops work. A real stop is only what this list names: a short list a person writes, one line a
stop. A Loop that never had one uses ``DEFAULT_STOPS`` (``loops.stops_json`` is NULL); an empty list
is a choice of its own (nothing stops) and is stored as ``[]``.

Anyone who may read the Loop reads the list (``loops:read``). Writing it is a signed-in person's
act at every stage of the Loop (``403 human_action_required`` for a key, whatever rights it holds),
with ``loops:write``, on a Loop that still takes writes (``409 loop_read_only``). A list holds 0 to
``STOPS_MAX_LINES`` lines, each a single line of 1 to ``STOP_MAX_CHARS`` characters once trimmed,
and no line twice (case-insensitive); a breach is ``422 stops_invalid`` naming each line and rule.

A wait on a Ticket may name the stop it is for (``TicketWorkService.set_wait``): ``match_stop``
finds the line by its text (trimmed, case-insensitive) or by its 1-based number written as text,
and a wait that names something else is ``422 not_a_stop``. The parsing, the checks and the match
are pure; the service reaches the board only through the board unit of work.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final, TypedDict
from uuid import uuid4

from pydantic import JsonValue

from ..core.context import ActorContext
from ..core.dates import iso_utc
from ..core.errors import ValidationFailure
from ..db.generated.board import LoopsRow
from ..repositories.board import BoardUnitOfWork
from .activity import activity_entry
from .lists import BoardChecks
from .loops_rules import ensure_writable, require_loop

DEFAULT_STOPS: Final[tuple[str, ...]] = (
    "Deployment to production",
    "Deleting data",
    "Money",
    "Something sent to people outside",
    "A new kind of personal data",
)
"""The stop list of a Loop whose person has not written one."""

STOPS_MAX_LINES: Final = 12
STOP_MAX_CHARS: Final = 140
STOPS_INVALID: Final = "stops_invalid"
NOT_A_STOP: Final = "not_a_stop"
NOT_A_STOP_MESSAGE: Final = (
    "That is not on this Loop's stop list. A choice that can be changed afterwards is a POC "
    "decision and something missing from a person is reported as missing; neither stops work."
)


class StopList(TypedDict):
    """A Loop's stop list as the API answers it; ``is_default`` while no person has written one."""

    stops: list[str]
    is_default: bool


# --- pure: reading, checking and matching --------------------------------------------------------


def parse_stops(stops_json: str | None) -> StopList:
    """The list ``loops.stops_json`` stores: NULL is the default list. A value that is not a JSON
    array of strings, which only a hand-edited database can hold, reads as the default too."""
    if stops_json is None:
        return {"stops": list(DEFAULT_STOPS), "is_default": True}
    try:
        value: JsonValue = json.loads(stops_json)
    except ValueError:
        return {"stops": list(DEFAULT_STOPS), "is_default": True}
    if not isinstance(value, list):
        return {"stops": list(DEFAULT_STOPS), "is_default": True}
    lines: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return {"stops": list(DEFAULT_STOPS), "is_default": True}
        lines.append(item)
    return {"stops": lines, "is_default": False}


def loop_stops(loop: LoopsRow) -> StopList:
    return parse_stops(loop.stops_json)


def stop_problems(lines: Sequence[str]) -> list[str]:
    """Why ``lines`` is not a stop list, one sentence a problem; empty when it is one. Each line
    is judged as it reads once trimmed, and a line is named by its 1-based number."""
    problems: list[str] = []
    if len(lines) > STOPS_MAX_LINES:
        problems.append(f"The list has {len(lines)} lines, at most {STOPS_MAX_LINES}.")
    seen: dict[str, int] = {}
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            problems.append(f"Line {number} is empty.")
            continue
        if "\n" in line or "\r" in line:
            problems.append(f"Line {number} is more than one line.")
        if len(line) > STOP_MAX_CHARS:
            problems.append(f"Line {number} has {len(line)} characters, at most {STOP_MAX_CHARS}.")
        folded = line.casefold()
        if folded in seen:
            problems.append(f"Line {number} repeats line {seen[folded]}.")
        else:
            seen[folded] = number
    return problems


def checked_stops(lines: Sequence[str]) -> list[str]:
    """The trimmed lines, or ``422 stops_invalid`` with every problem in its details."""
    problems = stop_problems(lines)
    if problems:
        raise ValidationFailure(
            "The stop list is not valid: " + " ".join(problems[:5]),
            code=STOPS_INVALID,
            details={"errors": problems, "error_count": len(problems)},
        )
    return [line.strip() for line in lines]


def match_stop(stops: Sequence[str], given: str) -> str | None:
    """The line of ``stops`` that ``given`` names, as the list holds it: by its text (trimmed,
    case-insensitive) or by its 1-based number written as text (``"2"``); ``None`` when it names
    none. A line whose text is a number is found by its text first."""
    wanted = given.strip()
    if not wanted:
        return None
    folded = wanted.casefold()
    for line in stops:
        if line.strip().casefold() == folded:
            return line
    if wanted.isdecimal():
        number = int(wanted)
        if 1 <= number <= len(stops):
            return stops[number - 1]
    return None


def require_stop(loop: LoopsRow, given: str) -> str:
    """The stop-list line a wait names, or ``422 not_a_stop`` with the Loop's list."""
    stops = loop_stops(loop)["stops"]
    line = match_stop(stops, given)
    if line is None:
        raise ValidationFailure(NOT_A_STOP_MESSAGE, code=NOT_A_STOP, details={"stops": stops})
    return line


# --- the service ---------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class LoopStopService:
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

    def read(self, actor: ActorContext, board_id: str, loop_id: str) -> StopList:
        actor.require("loops:read")
        self.boards.require_row(board_id)
        with self.store.reader(board_id) as repos:
            return loop_stops(require_loop(repos, loop_id))

    def write(
        self, actor: ActorContext, board_id: str, loop_id: str, lines: Sequence[str]
    ) -> StopList:
        """The person's list replaces the Loop's; writing the list it already holds changes
        nothing. An empty list is stored as ``[]``: nothing stops."""
        actor.require_human("Editing the stop list")
        actor.require("loops:write")
        stops = checked_stops(lines)
        self.boards.ensure_active(board_id)
        with self.store.writer(board_id) as repos:
            loop = require_loop(repos, loop_id)
            ensure_writable(loop)
            before = loop_stops(loop)
            if not before["is_default"] and before["stops"] == stops:
                return before
            now = iso_utc(self._clock())
            repos.loops.set_stops(loop_id, json.dumps(stops), now=now)
            repos.activity.add(
                activity_entry(
                    actor,
                    action="loop.stops_changed",
                    entity_type="loop",
                    entity_id=loop_id,
                    changes={
                        "stops": stops,
                        "before": before["stops"],
                        "was_default": before["is_default"],
                    },
                    entry_id=self._new_id(),
                    timestamp=now,
                )
            )
        return {"stops": stops, "is_default": False}


__all__ = [
    "DEFAULT_STOPS",
    "NOT_A_STOP",
    "NOT_A_STOP_MESSAGE",
    "STOPS_INVALID",
    "STOPS_MAX_LINES",
    "STOP_MAX_CHARS",
    "LoopStopService",
    "StopList",
    "checked_stops",
    "loop_stops",
    "match_stop",
    "parse_stops",
    "require_stop",
    "stop_problems",
]
