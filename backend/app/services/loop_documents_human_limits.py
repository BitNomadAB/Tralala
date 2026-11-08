"""The analysis brief as a sign: its limits, the check a new brief is held to, and the refusal.

A person reads the analysis brief to decide, so its form is fixed by that decision, not by the
material: the verdict in one line of at most ``SIGN_MAX_VERDICT_WORDS`` words (``verdict_line``),
at most ``SIGN_MAX_ITEMS`` reasons (``obstacles``) and as many points for and against, at most
``SIGN_MAX_DECISIONS`` questions to the person, each on one line, and how big the work is
(``size``: small, medium or large and one sentence). Every visible item holds at most
``SIGN_MAX_CHARS`` characters. The counts are the face's (``plain_text.word_count`` and
``sentence_count``), so a brief and a Ticket count words and sentences alike.

The rest of the brief's rules (every material finding named by some item, only known ids, plain
text) stay in ``loop_documents_human``; the sign is checked first, and a refusal names both, so one
round fixes everything. Every problem names the field and the rule (``BriefProblem``), and its
message is the sentence a writer reads, for example ``Brief, obstacles: 4 items, at most 3.``. A
list item is named by its 0-based index (``decisions[1].question``). A refusal is
``422 brief_invalid`` with the messages in its details.

A brief stored before the sign existed is read as it is (``schemas/briefs.py`` parses the older,
looser limits) and never checked again: the sign holds what is written, not what was. Everything
here is pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from ..core.errors import ValidationFailure
from ..schemas.briefs import (
    SIGN_MAX_CHARS,
    SIGN_MAX_DECISIONS,
    SIGN_MAX_ITEMS,
    SIGN_MAX_VERDICT_WORDS,
    HumanBrief,
)
from .plain_text import sentence_count, word_count

BRIEF_INVALID = "brief_invalid"
# A content refusal (coverage, ids, wording) keeps the code it had before the sign.
BRIEF_REJECTED = "brief_rejected"
SIGN_MAX_SIZE_SENTENCES = 1
# A refusal lists at most this many messages; the count says how many there were.
SIGN_MAX_ERRORS = 20
# The one example question every writer of an analysis brief is shown: one line, the choice a
# person makes, in their words.
SIGN_QUESTION_EXAMPLE = (
    "Do we keep the addresses of people who never confirm, and if so, for how long?"
)
_MISSING = {
    "verdict_line": f"Say the verdict in one line of at most {SIGN_MAX_VERDICT_WORDS} words.",
    "size": "Say how big the work is: small, medium or large, and why in one sentence.",
}


class BriefProblemEntry(TypedDict):
    """A problem in a refusal's details, for a log or a later count of repairs."""

    field: str
    rule: str


@dataclass(frozen=True, slots=True)
class BriefProblem:
    """One thing a brief got wrong about the sign: the field (``obstacles[0].text`` for an item),
    the rule (``missing``, ``words``, ``lines``, ``sentences``, ``too_many``, ``chars``) and the
    sentence a writer reads."""

    field: str
    rule: str
    message: str

    def entry(self) -> BriefProblemEntry:
        return {"field": self.field, "rule": self.rule}


class _Found:
    def __init__(self) -> None:
        self.problems: list[BriefProblem] = []

    def add(self, field: str, rule: str, text: str) -> None:
        self.problems.append(BriefProblem(field, rule, f"Brief, {field}: {text}"))

    def line(self, field: str, text: str) -> None:
        lines = len(text.splitlines())
        if lines > 1:
            self.add(field, "lines", f"{lines} lines, at most 1.")

    def chars(self, field: str, text: str) -> None:
        if len(text) > SIGN_MAX_CHARS:
            self.add(field, "chars", f"{len(text)} characters, at most {SIGN_MAX_CHARS}.")

    def count(self, field: str, items: int, most: int) -> None:
        if items > most:
            self.add(field, "too_many", f"{items} items, at most {most}.")

    def texts(self, field: str, texts: Sequence[str], most: int, name: str = "text") -> None:
        self.count(field, len(texts), most)
        for index, text in enumerate(texts):
            path = f"{field}[{index}].{name}"
            self.chars(path, text)
            if name == "question":
                self.line(path, text)


def sign_findings(brief: HumanBrief) -> list[BriefProblem]:
    """Every way the brief breaks the sign, in the order a writer reads the brief: the verdict line,
    the reasons, the points for and against, the questions, the size."""
    found = _Found()
    verdict = brief.verdict_line
    if not verdict.strip():
        found.add("verdict_line", "missing", f"missing. {_MISSING['verdict_line']}")
    else:
        words = word_count(verdict)
        if words > SIGN_MAX_VERDICT_WORDS:
            found.add("verdict_line", "words", f"{words} words, at most {SIGN_MAX_VERDICT_WORDS}.")
        found.line("verdict_line", verdict)
    found.texts("obstacles", [item.text for item in brief.obstacles], SIGN_MAX_ITEMS)
    found.texts("pros", [item.text for item in brief.pros], SIGN_MAX_ITEMS)
    found.texts("cons", [item.text for item in brief.cons], SIGN_MAX_ITEMS)
    found.texts(
        "decisions", [item.question for item in brief.decisions], SIGN_MAX_DECISIONS, "question"
    )
    if brief.size is None:
        found.add("size", "missing", f"missing. {_MISSING['size']}")
    else:
        sentences = sentence_count(brief.size.text)
        if sentences > SIGN_MAX_SIZE_SENTENCES:
            most = SIGN_MAX_SIZE_SENTENCES
            found.add("size.text", "sentences", f"{sentences} sentences, at most {most}.")
        found.chars("size.text", brief.size.text)
    return found.problems


class BriefRefusal(ValidationFailure):
    """A brief that broke a rule, as a hand-in's ``422`` and a generation's repair see it.

    ``problems`` are the sign's (typed, for a repair request or a log); ``others`` are the content
    rules the same brief broke (``loop_documents_human.check_brief``) or why it did not parse, each
    as its text. The code is ``brief_invalid`` when the sign is broken, else ``brief_rejected``, the
    code a content refusal has always had. The details hold every message (at most
    ``SIGN_MAX_ERRORS``) under ``errors``, their count, the sign's problems under ``rules`` and the
    others under ``other_errors``; the first five make the message."""

    def __init__(self, problems: Sequence[BriefProblem], others: Sequence[str] = ()) -> None:
        self.problems = tuple(problems)
        self.others = tuple(others)
        messages = self.messages()
        details: dict[str, object] = {
            "errors": messages,
            "error_count": len(self.problems) + len(self.others),
            "rules": [dict(problem.entry()) for problem in self.problems[:SIGN_MAX_ERRORS]],
        }
        if self.others:
            details["other_errors"] = list(self.others[:SIGN_MAX_ERRORS])
        super().__init__(
            "The brief was not accepted: " + " ".join(messages[:5]),
            code=BRIEF_INVALID if self.problems else BRIEF_REJECTED,
            details=details,
        )

    def messages(self) -> list[str]:
        """Every message the writer is told to fix: the sign's first, then the others."""
        sign = [problem.message for problem in self.problems]
        return [*sign, *self.others][:SIGN_MAX_ERRORS]

    def lines(self) -> str:
        """``messages``, one per line."""
        return "\n".join(self.messages())


def refuse_sign(problems: Sequence[BriefProblem], others: Sequence[str] = ()) -> None:
    """Raise ``BriefRefusal`` (``422 brief_invalid``) for the sign's ``problems`` with the content
    problems of the same brief after them, or nothing when the sign holds."""
    if problems:
        raise BriefRefusal(problems, others)


__all__ = [
    "BRIEF_INVALID",
    "BRIEF_REJECTED",
    "SIGN_MAX_ERRORS",
    "SIGN_MAX_SIZE_SENTENCES",
    "SIGN_QUESTION_EXAMPLE",
    "BriefProblem",
    "BriefProblemEntry",
    "BriefRefusal",
    "refuse_sign",
    "sign_findings",
]
