"""The address in the web UI where a person takes a decision that no key can take.

A coding session can wait for a person: an analysis or a RoadMap to approve, implementation or QA
to accept, a Ticket's wait to clear, a human-only Ticket to confirm, Info to edit. This module is
the one place that turns such a decision and its ids into the address of the tab, dialog or button
where the person takes it, so every answer that names one points at the same place.

The paths mirror the frontend: the Loop page is ``loopPagePath`` and the Ticket page
``ticketPagePath`` (``features/cards/ticketRules.ts``), the Plan tab ``loopHref`` with
``?tab=plan`` (``features/loops/loopNextAction.ts``), each id URL-encoded as
``encodeURIComponent`` does. ``dialog=completion``, ``focus=clear-wait`` and ``focus=confirm`` are a
contract with the web UI, which opens the dialog or focuses the button they name.

An id reaches the path only as the text of a UUID, so no path is built from free text (AGENTS.md
rule 2). The server does not know the host a person reaches it by and never takes it from a
request's ``Host`` or ``X-Forwarded-*`` headers: the address is absolute only when the installation
sets its public address (``Settings.public_url``, ``TRALALA_PUBLIC_URL``), a path inside Tralala
otherwise.
"""

from __future__ import annotations

import re
from typing import Literal, assert_never
from urllib.parse import quote

Decision = Literal["analysis", "roadmap", "implementation", "qa", "wait", "confirmation", "info"]

# A UUID as text: 32 hex digits in groups of 8-4-4-4-12, in either case. ``uuid.UUID`` also takes
# braces, a ``urn:uuid:`` prefix, missing hyphens, underscores and whitespace; none is an id here.
_UUID_TEXT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _segment(name: str, value: str) -> str:
    """``value`` as one path segment, refused unless it is a UUID.

    The id is kept as given, so the address is the one the frontend builds from the same id, and
    encoded as ``encodeURIComponent`` encodes it. A UUID's text needs no escaping, so the encoding
    changes nothing; it is the guarantee that a segment never carries a ``/``, ``?`` or ``#``.
    """
    if _UUID_TEXT.fullmatch(value) is None:
        raise ValueError(f"{name} must be a UUID")
    return quote(value, safe="")


def _ticket_page(loop_page: str, decision: Decision, card_id: str | None) -> str:
    if card_id is None:
        raise ValueError(f"a {decision} is taken on a Ticket's page, so it needs card_id")
    return f"{loop_page}/tickets/{_segment('card_id', card_id)}"


def decision_path(
    decision: Decision,
    *,
    board_id: str,
    loop_id: str,
    card_id: str | None = None,
) -> str:
    """The path inside Tralala where a person takes ``decision``.

    A wait and a confirmation are taken on the Ticket's page and need ``card_id``; every other
    decision is taken on the Loop page and takes none. A ``ValueError`` names the id that is
    missing, superfluous or not a UUID.
    """
    loop_page = f"/boards/{_segment('board_id', board_id)}/loops/{_segment('loop_id', loop_id)}"
    match decision:
        case "wait":
            return f"{_ticket_page(loop_page, decision, card_id)}?focus=clear-wait"
        case "confirmation":
            return f"{_ticket_page(loop_page, decision, card_id)}?focus=confirm"
        case "analysis":
            query = "tab=plan&doc=analysis"
        case "roadmap":
            query = "tab=plan&doc=roadmap"
        case "info":
            query = "tab=plan&doc=info"
        case "implementation" | "qa":
            query = "dialog=completion"
        case _:
            assert_never(decision)
    if card_id is not None:
        raise ValueError(f"{decision} is taken on the Loop page, so it takes no card_id")
    return f"{loop_page}?{query}"


def decision_link(
    decision: Decision,
    *,
    board_id: str,
    loop_id: str,
    card_id: str | None = None,
    public_url: str | None,
) -> str:
    """The address of ``decision``: ``public_url`` followed by its path, or the path alone.

    ``public_url`` is ``Settings.public_url``, which its validator has checked and stripped of a
    trailing slash; one left on is dropped here as well, so the path never follows a ``//``. Without
    it the answer is the path, which the reader completes with the address they open Tralala at.
    """
    path = decision_path(decision, board_id=board_id, loop_id=loop_id, card_id=card_id)
    return f"{(public_url or '').rstrip('/')}{path}"
