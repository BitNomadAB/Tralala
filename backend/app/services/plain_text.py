"""What text for people must not hold, and how it is counted: code formatting, a file path or a
file name, a code symbol, an id or a finding id; words and sentences.

The brief a person reads (``loop_documents_human``), the face of a Ticket (``ticket_face``) and a
discussion answer's sign (``discussion_answers``) are held to the same rules and counted alike, so
they live here, pure and without a service import, and each imports them;
``loop_documents_human`` re-exports ``text_problems``. ``plain_rules`` is the check the face and the
answer share: every rule a text breaks, as the rule's name and the phrase a writer reads.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

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


# Words that look like a code symbol and are not one. ``RoadMap`` is the product's own word for a
# plan; extend the tuple, with the reason, when another product word needs it.
ALLOWED_WORDS: tuple[str, ...] = ("RoadMap",)

# A run of sentence ends followed by whitespace or the end of the text.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
# A file name without a folder (``BriefView.tsx``); a path with a folder is ``text_problems``'.
_FILE_NAME = re.compile(
    r"(?<![\w/\\.-])[\w-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|json|md|css|scss|html|yml|yaml|toml"
    r"|sql|sqlite|txt|sh|ps1|cfg|ini|lock|go|rs|java|kt|cs|cpp|rb|php|vue|svelte|xml|env)\b",
    re.I,
)
_SNAKE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]")
_CAMEL = re.compile(r"[a-z][A-Z]")
_OPERATORS = ("()", "::", "->", "=>", "${")
_CURLY = "\u2018\u2019\u201c\u201d"
_EDGE = "\"'`.,;:!?()[]{}<>" + _CURLY
_QUOTES = "\"'.,;!?" + _CURLY
# What ``text_problems`` says, as the rule a problem breaks and the words a writer's message uses.
_TEXT_RULES: tuple[tuple[str, str, str], ...] = (
    ("contains a code fence", "code_fence", "contains a code fence"),
    ("contains code", "code_span", "contains code"),
    ("contains a file path", "file_path", "looks like a file path"),
    ("contains an id", "id", "contains an id"),
    ("contains a finding id", "finding_id", "contains a finding id"),
)


# --- counting ------------------------------------------------------------------------------------


def word_count(text: str) -> int:
    """The whitespace-separated tokens of ``text``."""
    return len(text.split())


def sentence_count(text: str) -> int:
    """The sentences of ``text``: each run of ``.``, ``!`` or ``?`` followed by whitespace or the
    end ends one, and text after the last end is one more. An abbreviation ends a sentence too
    (``e.g. this`` is two), which the generous limit allows for; ``3.5`` ends none. An empty text
    has none."""
    stripped = text.strip()
    if not stripped:
        return 0
    ends = list(_SENTENCE_END.finditer(stripped))
    tail = stripped[ends[-1].end() :] if ends else stripped
    return len(ends) + (1 if tail.strip() else 0)


# --- code symbols and the shared check -----------------------------------------------------------


def _tokens(text: str) -> Iterator[str]:
    for raw in text.split():
        token = raw.strip(_EDGE)
        for possessive in ("'s", "\u2019s"):
            token = token.removesuffix(possessive)
        if token:
            yield token


def code_symbol(text: str) -> str | None:
    """The first token of ``text`` that looks like a code symbol: ``snake_case``, a lowercase letter
    followed by an uppercase one (``loopQuestions``), or ``()``, ``::``, ``->``, ``=>`` or ``${``.
    A word in ``ALLOWED_WORDS``, a link, a file name and code already in backticks are left to
    their own rules."""
    for raw in text.split():
        operator = next((mark for mark in _OPERATORS if mark in raw), None)
        if operator is not None and "`" not in raw:
            return raw.strip(_QUOTES) or operator
    for token in _tokens(text):
        if (
            token in ALLOWED_WORDS
            or token.removesuffix("s") in ALLOWED_WORDS
            or "`" in token
            or token.lower().startswith(("http://", "https://"))
            or _FILE_NAME.search(token)
        ):
            continue
        if _SNAKE.search(token) or _CAMEL.search(token):
            return token
    return None


def plain_rules(text: str) -> list[tuple[str, str]]:
    """``(rule, phrase)`` for every plain-text rule ``text`` breaks, in a fixed order: the rules of
    ``text_problems`` (``code_fence``, ``code_span``, ``file_path``, ``id``, ``finding_id``), then a
    file name without a folder (``file_path``) and a code symbol (``code_symbol``). The phrase is
    what a writer reads, with the offending text in brackets: ``looks like a file path
    (Banner.tsx)``."""
    found: list[tuple[str, str]] = []
    path_found = False
    for problem in text_problems(text, []):
        for prefix, rule, phrase in _TEXT_RULES:
            if problem.startswith(prefix):
                shown = problem.partition("(")[2].rpartition(")")[0]
                path_found = path_found or rule == "file_path"
                found.append((rule, f"{phrase} ({shown})" if shown else phrase))
                break
    name = None if path_found else _FILE_NAME.search(text)
    if name is not None:
        found.append(("file_path", f"looks like a file path ({name.group(0)})"))
    symbol = code_symbol(text)
    if symbol is not None:
        found.append(("code_symbol", f"looks like a code symbol ({symbol})"))
    return found


__all__ = [
    "ALLOWED_WORDS",
    "code_symbol",
    "plain_rules",
    "sentence_count",
    "text_problems",
    "word_count",
]
