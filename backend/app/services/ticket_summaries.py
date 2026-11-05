"""A Ticket's short summary: who wrote it, whether it still matches the Ticket, and the excerpt a
list shows when nobody has written one.

Pure functions over a card's row, so the service, the views and the worker tools agree on one rule.
A summary remembers the title and description it was written from as a hash; when either changes
the summary is still shown, marked stale, so a reader knows to write a new one.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final, Literal

from ..core.context import ActorContext
from ..db.generated.board import CardsRow

type SummarySource = Literal["", "plan", "person", "agent"]

EXCERPT_CHARS: Final = 200
"""The longest excerpt of a description a list shows in place of a missing summary."""

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKUP = re.compile(r"[`*_>#|~]+")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def summary_basis(title: str, description: str) -> str:
    """The hash of what a summary describes: the title and the description it was written from."""
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


def summary_source(actor: ActorContext) -> SummarySource:
    """Who wrote a summary through a card write: a signed-in person or an agent's token."""
    return "person" if actor.is_user else "agent"


def summary_stale(row: CardsRow) -> bool:
    """A written summary whose Ticket's title or description changed after it was written."""
    if not row.summary:
        return False
    return row.summary_basis_sha256 != summary_basis(row.title, row.description)


def excerpt(description: str, limit: int = EXCERPT_CHARS) -> str:
    """The start of a description as plain text: links keep their text, Markdown marks go, and
    the text ends at the last whole sentence (or word) that fits within ``limit``."""
    text = _LIST_MARKER.sub("", _LINK.sub(r"\1", description))
    text = " ".join(_MARKUP.sub(" ", text).split())
    if len(text) <= limit:
        return text
    head = text[:limit]
    sentences = [match.end() for match in _SENTENCE_END.finditer(head + " ")]
    if sentences and sentences[-1] >= limit // 2:
        return head[: sentences[-1]].rstrip()
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(" ,;:-") + "…"


__all__ = [
    "EXCERPT_CHARS",
    "SummarySource",
    "excerpt",
    "summary_basis",
    "summary_source",
    "summary_stale",
]
