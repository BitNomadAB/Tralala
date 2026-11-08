"""The Ticket's face for people: its limits, the check every writer is held to, and its storage.

A Ticket's face is what a person reads of it by default: the summary (its own column), why it is
needed, what happens if we skip it, up to three points for and three against, and one to five
concrete steps. Whoever writes it (a RoadMap handed in by a worker or written by a generation, a
worker's unplanned Ticket, a person's edit) is held to the same template here, deterministically:
word and sentence counts, list lengths, and the plain-text rules of the brief
(``plain_text.text_problems``: no code fence, code span, file path, UUID or finding id)
plus a code-symbol rule, since a face says what changes for the person, never where in the code.
Nothing here judges text with a model.

Every problem names the Ticket, the field and the rule (``FaceProblem``), and its message is the
sentence a writer reads to fix it, for example ``Ticket PLN-023, steps: 7 items, at most 5. Split
the Ticket into two.``. A list item is named by its 0-based index, as a JSON path is
(``steps[2]``). A refusal is ``422 face_invalid`` with the messages in its details.

The face is stored as a JSON object (``why``, ``if_skipped``, ``pros``, ``cons``, ``steps``) in
``cards.face`` and ``loop_plan_items.face``; the empty string is no face, which every Ticket
written before the face existed has. Everything here is pure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TypedDict

from pydantic import JsonValue

from ..core.errors import ValidationFailure
from ..schemas.loops import PlanPayload
from .plain_text import text_problems

FACE_MAX_SUMMARY_WORDS = 20
FACE_MAX_SENTENCES = 3
FACE_MAX_POINTS = 3
FACE_MIN_STEPS = 1
FACE_MAX_STEPS = 5
# Words that look like a code symbol and are not one. ``RoadMap`` is the product's own word for a
# plan; extend the tuple, with the reason, when another product word needs it.
FACE_ALLOWED_WORDS: tuple[str, ...] = ("RoadMap",)
# The face's fields besides the summary, in the order a writer writes them.
FACE_FIELDS: tuple[str, ...] = ("why", "if_skipped", "pros", "cons", "steps")
# A refusal lists at most this many messages; the count says how many there were.
FACE_MAX_ERRORS = 20
FACE_INVALID = "face_invalid"
# The one good and the one bad step every writer is shown: the RoadMap prompt (``FACE_RULE`` in
# ``loop_generation_prompts``) and ``write_roadmap``'s description in the worker catalogue. The
# good one keeps the template; the bad one names a code symbol in a file, which a step never does.
FACE_STEP_GOOD = (
    "Under each open question, put an answer field and a Go on without my answer button."
)
FACE_STEP_BAD = "Add QuestionList to BriefView.tsx."

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
# What ``text_problems`` says, as the rule a problem breaks and the words a face's message uses.
_TEXT_RULES: tuple[tuple[str, str, str], ...] = (
    ("contains a code fence", "code_fence", "contains a code fence"),
    ("contains code", "code_span", "contains code"),
    ("contains a file path", "file_path", "looks like a file path"),
    ("contains an id", "id", "contains an id"),
    ("contains a finding id", "finding_id", "contains a finding id"),
)
_WHERE_IN_CODE = " Say what changes for the person, not where in the code."
_MISSING = {
    "summary": f"Say in at most {FACE_MAX_SUMMARY_WORDS} words what the Ticket means.",
    "why": f"Say in at most {FACE_MAX_SENTENCES} sentences why it is needed.",
    "if_skipped": f"Say in at most {FACE_MAX_SENTENCES} sentences what happens if we skip it.",
    "steps": "Write one to five steps, each saying what changes for the person.",
}


class TicketFace(TypedDict):
    """The face as ``cards.face`` and ``loop_plan_items.face`` store it; the summary has its own
    column."""

    why: str
    if_skipped: str
    pros: list[str]
    cons: list[str]
    steps: list[str]


class FaceView(TypedDict):
    """The face as ``read_ticket`` and the card responses show it, the summary included."""

    summary: str
    why: str
    if_skipped: str
    pros: list[str]
    cons: list[str]
    steps: list[str]


class FaceProblemEntry(TypedDict):
    """A problem in a refusal's details, for a log or a later count of repairs."""

    ticket_id: str
    field: str
    rule: str


@dataclass(frozen=True, slots=True)
class FaceProblem:
    """One thing a face got wrong: the Ticket (as its writer named it), the field (``steps[2]``
    for an item), the rule (``words``, ``sentences``, ``too_many``, ``missing``, ``empty_item``,
    ``code_fence``, ``code_span``, ``file_path``, ``id``, ``finding_id``, ``code_symbol``) and the
    sentence a writer reads."""

    ticket_id: str
    field: str
    rule: str
    message: str

    def entry(self) -> FaceProblemEntry:
        return {"ticket_id": self.ticket_id, "field": self.field, "rule": self.rule}


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


# --- the rules -----------------------------------------------------------------------------------


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
    A word in ``FACE_ALLOWED_WORDS``, a link, a file name and code already in backticks are left to
    their own rules."""
    for raw in text.split():
        operator = next((mark for mark in _OPERATORS if mark in raw), None)
        if operator is not None and "`" not in raw:
            return raw.strip(_QUOTES) or operator
    for token in _tokens(text):
        if (
            token in FACE_ALLOWED_WORDS
            or token.removesuffix("s") in FACE_ALLOWED_WORDS
            or "`" in token
            or token.lower().startswith(("http://", "https://"))
            or _FILE_NAME.search(token)
        ):
            continue
        if _SNAKE.search(token) or _CAMEL.search(token):
            return token
    return None


def _text_rules(text: str) -> Iterator[tuple[str, str]]:
    """``(rule, phrase)`` for every plain-text rule ``text`` breaks."""
    path_found = False
    for problem in text_problems(text, []):
        for prefix, rule, phrase in _TEXT_RULES:
            if problem.startswith(prefix):
                shown = problem.partition("(")[2].rpartition(")")[0]
                path_found = path_found or rule == "file_path"
                yield rule, f"{phrase} ({shown})" if shown else phrase
                break
    name = None if path_found else _FILE_NAME.search(text)
    if name is not None:
        yield "file_path", f"looks like a file path ({name.group(0)})"
    symbol = code_symbol(text)
    if symbol is not None:
        yield "code_symbol", f"looks like a code symbol ({symbol})"


class _Found:
    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        self.problems: list[FaceProblem] = []

    def add(self, field: str, rule: str, text: str) -> None:
        message = f"Ticket {self.ticket_id}, {field}: {text}"
        self.problems.append(FaceProblem(self.ticket_id, field, rule, message))

    def plain(self, field: str, text: str, *, step: bool = False) -> None:
        for rule, phrase in _text_rules(text):
            advice = _WHERE_IN_CODE if step and rule in ("file_path", "code_symbol") else ""
            self.add(field, rule, f"{phrase}.{advice}")

    def prose(self, field: str, text: str) -> None:
        if not text.strip():
            self.add(field, "missing", f"missing. {_MISSING[field]}")
            return
        sentences = sentence_count(text)
        if sentences > FACE_MAX_SENTENCES:
            self.add(field, "sentences", f"{sentences} sentences, at most {FACE_MAX_SENTENCES}.")
        self.plain(field, text)

    def items(self, field: str, values: Sequence[str], *, most: int, least: int = 0) -> None:
        if least and not any(value.strip() for value in values):
            self.add(field, "missing", f"missing. {_MISSING[field]}")
            return
        if len(values) > most:
            split = " Split the Ticket into two." if field == "steps" else ""
            self.add(field, "too_many", f"{len(values)} items, at most {most}.{split}")
        for index, value in enumerate(values):
            path = f"{field}[{index}]"
            if not value.strip():
                self.add(path, "empty_item", "empty. Remove it or write it.")
                continue
            self.plain(path, value, step=field == "steps")


def face_missing(
    summary: str,
    why: str,
    if_skipped: str,
    pros: Sequence[str],
    cons: Sequence[str],
    steps: Sequence[str],
) -> bool:
    """True when every field of the face is empty: the Ticket has no face."""
    texts = (summary, why, if_skipped, *pros, *cons, *steps)
    return not any(text.strip() for text in texts)


def face_findings(
    ticket_id: str,
    summary: str,
    why: str,
    if_skipped: str,
    pros: Sequence[str],
    cons: Sequence[str],
    steps: Sequence[str],
) -> list[FaceProblem]:
    """Every problem of the face, field by field in the order a writer writes them. The face is
    checked whole: an empty summary, why, if_skipped or step list is a problem of its own."""
    found = _Found(ticket_id)
    if not summary.strip():
        found.add("summary", "missing", f"missing. {_MISSING['summary']}")
    else:
        words = word_count(summary)
        if words > FACE_MAX_SUMMARY_WORDS:
            found.add("summary", "words", f"{words} words, at most {FACE_MAX_SUMMARY_WORDS}.")
        found.plain("summary", summary)
    found.prose("why", why)
    found.prose("if_skipped", if_skipped)
    found.items("pros", pros, most=FACE_MAX_POINTS)
    found.items("cons", cons, most=FACE_MAX_POINTS)
    found.items("steps", steps, most=FACE_MAX_STEPS, least=FACE_MIN_STEPS)
    return found.problems


def face_problems(
    ticket_id: str,
    summary: str,
    why: str,
    if_skipped: str,
    pros: Sequence[str],
    cons: Sequence[str],
    steps: Sequence[str],
) -> list[str]:
    """One message per problem of the face (``face_findings``); empty when it keeps the
    template."""
    return [
        problem.message
        for problem in face_findings(ticket_id, summary, why, if_skipped, pros, cons, steps)
    ]


def plan_face_findings(payload: PlanPayload) -> list[FaceProblem]:
    """Every problem of every planned Ticket's face, each Ticket named by the id its writer gave
    it. A RoadMap must carry a face on every Ticket, so a missing one is checked whole too."""
    return [
        problem
        for phase in payload.phases
        for ticket in phase.tickets
        for problem in face_findings(
            ticket.id,
            ticket.summary,
            ticket.why,
            ticket.if_skipped,
            ticket.pros,
            ticket.cons,
            ticket.steps,
        )
    ]


class FaceRefusal(ValidationFailure):
    """``422 face_invalid``: every message (at most ``FACE_MAX_ERRORS``) in the details' ``errors``
    and the structured problems in ``faces``; the first five make the message. ``problems`` keeps
    them all, typed, for a repair request or a log.

    ``others`` are the other problems a generation found in the same answer (a plan rule, an
    unknown label), each as its text: they follow the face's messages in ``lines`` and sit under
    ``other_errors`` in the details, so one repair round names everything and the face comes
    first."""

    def __init__(self, problems: Sequence[FaceProblem], others: Sequence[str] = ()) -> None:
        self.problems = tuple(problems)
        self.others = tuple(others)
        messages = [problem.message for problem in self.problems]
        shown = messages[:FACE_MAX_ERRORS]
        details: dict[str, object] = {
            "errors": shown,
            "error_count": len(messages),
            "faces": [dict(problem.entry()) for problem in self.problems[:FACE_MAX_ERRORS]],
        }
        if self.others:
            details["other_errors"] = list(self.others)
        super().__init__(
            "The face for people does not keep its template: " + " ".join(shown[:5]),
            code=FACE_INVALID,
            details=details,
        )

    def messages(self) -> list[str]:
        """Every message the model is told to fix: the face's first, then the other problems."""
        return [*(problem.message for problem in self.problems[:FACE_MAX_ERRORS]), *self.others]

    def lines(self) -> str:
        """``messages``, one per line."""
        return "\n".join(self.messages())


def refuse_face(problems: Sequence[FaceProblem]) -> None:
    """Raise ``FaceRefusal`` for ``problems``, or nothing when there is none."""
    if problems:
        raise FaceRefusal(problems)


# --- storage -------------------------------------------------------------------------------------


def make_face(
    why: str = "",
    if_skipped: str = "",
    pros: Sequence[str] = (),
    cons: Sequence[str] = (),
    steps: Sequence[str] = (),
) -> TicketFace:
    return {
        "why": why,
        "if_skipped": if_skipped,
        "pros": list(pros),
        "cons": list(cons),
        "steps": list(steps),
    }


def face_to_text(face: TicketFace) -> str:
    """The face as its column stores it; a face with every field empty is no face (``""``)."""
    if face_missing("", face["why"], face["if_skipped"], face["pros"], face["cons"], face["steps"]):
        return ""
    return json.dumps(
        {name: face[name] for name in FACE_FIELDS}, ensure_ascii=False, separators=(",", ":")
    )


def _strings(value: JsonValue) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = [item for item in value if isinstance(item, str)]
    return items if len(items) == len(value) else None


def face_from_text(text: str) -> TicketFace | None:
    """The stored face, or None for no face and for a column that does not hold one."""
    if not text:
        return None
    try:
        value: JsonValue = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    why = value.get("why", "")
    if_skipped = value.get("if_skipped", "")
    pros, cons, steps = (_strings(value.get(name, [])) for name in ("pros", "cons", "steps"))
    if not isinstance(why, str) or not isinstance(if_skipped, str):
        return None
    if pros is None or cons is None or steps is None:
        return None
    return make_face(why, if_skipped, pros, cons, steps)


def face_view(summary: str, text: str) -> FaceView | None:
    """The face a person reads, the summary included, or None when the Ticket has none."""
    face = face_from_text(text)
    if face is None:
        return None
    return {"summary": summary, **face}


__all__ = [
    "FACE_ALLOWED_WORDS",
    "FACE_FIELDS",
    "FACE_INVALID",
    "FACE_MAX_ERRORS",
    "FACE_MAX_POINTS",
    "FACE_MAX_SENTENCES",
    "FACE_MAX_STEPS",
    "FACE_MAX_SUMMARY_WORDS",
    "FACE_MIN_STEPS",
    "FACE_STEP_BAD",
    "FACE_STEP_GOOD",
    "FaceProblem",
    "FaceProblemEntry",
    "FaceRefusal",
    "FaceView",
    "TicketFace",
    "code_symbol",
    "face_findings",
    "face_from_text",
    "face_missing",
    "face_problems",
    "face_to_text",
    "face_view",
    "make_face",
    "plan_face_findings",
    "refuse_face",
    "sentence_count",
    "word_count",
]
