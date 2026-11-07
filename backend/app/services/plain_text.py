"""What text for people must not hold: code formatting, a file path, an id or a finding id.

The brief a person reads (``loop_documents_human``) and the face of a Ticket (``ticket_face``) are
held to the same rules, so they live here, pure and without a service import, and both import
them; ``loop_documents_human`` re-exports ``text_problems``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# What visible text must not hold. A code fence or an inline code span is code formatting; a token
# with a slash (or a backslash) and a file extension is a path (a URL's path is not, since a host
# name comes before it); a UUID is an id; ``F-1``, ``F01`` and ``[F01]`` are finding ids whatever
# the technical revision calls its findings.
_FENCE = re.compile(r"```|~~~")
_CODE_SPAN = re.compile(r"`[^`\n]+`")
_PATH = re.compile(r"(?<![\w/\\.:-])(?:[\w.-]+[/\\])+[\w-]+\.[A-Za-z][A-Za-z0-9]{0,7}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_FINDING_LIKE = re.compile(r"\[\s*[A-Za-z]{1,4}-?\d{1,4}\s*\]|\bF-\d{1,4}\b|\bF\d{2,4}\b")
_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"\d")


def _shown_ids(finding_ids: Sequence[str]) -> list[re.Pattern[str]]:
    """How each finding id shows up in prose. An id that looks like one (a letter and a digit, or a
    separator) is found as a whole word; a bare number or word only in square brackets, since
    ``3`` or ``mail`` alone is ordinary text."""
    patterns: list[re.Pattern[str]] = []
    for finding_id in finding_ids:
        escaped = re.escape(finding_id)
        looks_like_id = (
            _LETTER.search(finding_id) is not None and _DIGIT.search(finding_id) is not None
        ) or any(mark in finding_id for mark in "-_.")
        if looks_like_id and len(finding_id) >= 2:
            patterns.append(re.compile(rf"(?<![\w-]){escaped}(?![\w-])"))
        else:
            patterns.append(re.compile(rf"\[\s*{escaped}\s*\]"))
    return patterns


def text_problems(text: str, known_ids: Sequence[str]) -> list[str]:
    """Why ``text`` is not for people, as short phrases; empty when it is."""
    problems: list[str] = []
    if _FENCE.search(text):
        problems.append("contains a code fence")
    span = _CODE_SPAN.search(text)
    if span is not None:
        problems.append(f"contains code ({span.group(0)})")
    path = _PATH.search(text)
    if path is not None:
        problems.append(f"contains a file path ({path.group(0)})")
    uuid = _UUID.search(text)
    if uuid is not None:
        problems.append(f"contains an id ({uuid.group(0)})")
    shown = next(
        (match.group(0) for pattern in _shown_ids(known_ids) if (match := pattern.search(text))),
        None,
    ) or next((match.group(0) for match in _FINDING_LIKE.finditer(text)), None)
    if shown is not None:
        problems.append(f"contains a finding id ({shown}); ids belong in finding_ids only")
    return problems


__all__ = ["text_problems"]
