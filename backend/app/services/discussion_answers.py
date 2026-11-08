"""The standard a discussion answer follows: its fields, the prompt that asks for it, the schema a
provider may enforce, and the parser that reads it from an untrusted answer.

A participant answers a round with one JSON object (``DiscussionAnswer``, version 1): a position
from the analysis brief's verdict set, a one-sentence recommendation, reasons for and against, the
conditions of a yes, the questions it could not settle, and its confidence. The prose
(``reasoning``, or the text around the object) stays the message's ``content``; the structure is
stored beside it as ``answer_json``. An answer that never follows the shape is kept as prose with
the position ``unclear`` (``prose_answer``), never dropped.

The recommendation and the four lists are the answer's sign: what a person reads at a glance. They
are held to the face's discipline, counted and matched, never judged by a model: one sentence of
at most ``RECOMMENDATION_WORDS`` words, at most ``ITEMS`` items of at most ``ITEM_CHARS``
characters per list, and the plain-text rules (``plain_text.plain_rules``: no file path or file
name, code span or fence, code symbol, UUID or other id). The reasoning is the agents' side: long,
technical and unchecked but for its length. Every finding names the field, the rule and the text
(``AnswerFinding``), for example ``conditions[1]: looks like a file path (Banner.tsx)``; a list
item is named by its 0-based index. An answer stored under older, looser limits is read as it is
(``read_answer``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict, TypeIs

from pydantic import JsonValue

from .plain_text import plain_rules, sentence_count, word_count
from .runtime import ResponseSchema

VERSION = 1
POSITIONS = ("yes", "yes_with_conditions", "no", "unclear")
# The positions that support going ahead: consensus is every participant on this side.
GO = frozenset({"yes", "yes_with_conditions"})
CONFIDENCE = ("high", "medium", "low")
FORMATS = ("structured", "repaired", "prose")
LISTS = ("pros", "cons", "conditions", "open_questions")

RECOMMENDATION_WORDS = 20
RECOMMENDATION_SENTENCES = 1
# The schema's character cap on the recommendation: room for twenty words, not a rule of its own.
RECOMMENDATION_CHARS = 200
ITEMS = 3
ITEM_CHARS = 140
REASONING_CHARS = 8000
PROBLEM_CHARS = 300
# A repair request lists at most this many findings; the count says how many more there were.
MAX_FINDINGS = 20
# An answer longer than this is not searched for its object: a runaway answer stays prose.
SEARCH_CHARS = 60_000
SEARCH_OBJECTS = 50

_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL | re.IGNORECASE)


class DiscussionAnswer(TypedDict):
    """A participant's answer as it is stored and answered: the standard, and how it was read."""

    version: int
    format: str  # structured | repaired | prose
    position: str
    recommendation: str
    pros: list[str]
    cons: list[str]
    conditions: list[str]
    open_questions: list[str]
    confidence: str | None
    problem: str | None


class AnswerFindingEntry(TypedDict):
    """A finding as a log line carries it: the field and the rule, never the text."""

    field: str
    rule: str


@dataclass(frozen=True, slots=True)
class AnswerFinding:
    """One thing an answer got wrong: the field (``pros[2]`` for an item, ``answer`` for the whole
    text), the rule (``type``, ``choice``, ``missing``, ``words``, ``sentences``, ``chars``,
    ``too_many``, ``no_object``, or a plain-text rule: ``code_fence``, ``code_span``,
    ``file_path``, ``id``, ``finding_id``, ``code_symbol``) and the line a writer reads."""

    field: str
    rule: str
    message: str

    def entry(self) -> AnswerFindingEntry:
        return {"field": self.field, "rule": self.rule}


def finding(field: str, rule: str, text: str) -> AnswerFinding:
    """The finding whose line is ``field: text``."""
    return AnswerFinding(field, rule, f"{field}: {text}")


class AnswerShapeError(ValueError):
    """The answer does not follow the standard; every finding, one line each, says what to fix."""

    def __init__(self, findings: Sequence[AnswerFinding]) -> None:
        self.findings = tuple(findings)
        super().__init__("\n".join(item.message for item in self.findings))

    def lines(self) -> str:
        """The findings' lines: at most ``MAX_FINDINGS``, then how many more there were."""
        shown = [item.message for item in self.findings[:MAX_FINDINGS]]
        more = len(self.findings) - len(shown)
        return "\n".join([*shown, f"(and {more} more)"] if more else shown)

    def entries(self) -> list[AnswerFindingEntry]:
        """Every finding as a log line carries it."""
        return [item.entry() for item in self.findings]


def shape_error(field: str, rule: str, text: str) -> AnswerShapeError:
    """An ``AnswerShapeError`` of one finding."""
    return AnswerShapeError([finding(field, rule, text)])


def _is_object(value: JsonValue) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def answer_instructions() -> str:
    """The last section of a round's prompt: how to answer, and who reads which part."""
    return (
        "Answer with one JSON object and nothing else:\n"
        "{\n"
        '  "position": "yes" | "yes_with_conditions" | "no" | "unclear",\n'
        '  "recommendation": "what the person should do, in one sentence of at most '
        f'{RECOMMENDATION_WORDS} words",\n'
        '  "pros": ["for going ahead"],\n'
        '  "cons": ["against, and the risks"],\n'
        '  "conditions": ["what must hold; at least one when yes_with_conditions"],\n'
        '  "open_questions": ["what you cannot settle; at least one when unclear"],\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "reasoning": "your analysis from your role, in Markdown; name the participant you '
        'are answering"\n'
        "}\n"
        "`position` answers whether the person should go ahead with what the discussion goal "
        f"proposes. Each list holds at most {ITEMS} items of at most {ITEM_CHARS} characters; "
        "leave a list empty rather than repeat yourself. The recommendation and the lists are "
        "what the person reads: plain words, with no file name, code or id in them. The "
        "reasoning is read by the other agents and shown to the person as raw text, so it may be "
        f"as long and technical as it needs to be, up to {REASONING_CHARS} characters. A person "
        "decides; you advise."
    )


def answer_schema() -> ResponseSchema:
    """The standard as ``response_format`` carries it, for a provider that takes a schema."""
    item: dict[str, JsonValue] = {"type": "string", "maxLength": ITEM_CHARS}
    listed: dict[str, JsonValue] = {"type": "array", "items": item, "maxItems": ITEMS}
    return {
        "name": "discussion_answer",
        "schema": {
            "type": "object",
            "properties": {
                "position": {"type": "string", "enum": list(POSITIONS)},
                "recommendation": {"type": "string", "maxLength": RECOMMENDATION_CHARS},
                "pros": listed,
                "cons": listed,
                "conditions": listed,
                "open_questions": listed,
                "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                "reasoning": {"type": "string", "maxLength": REASONING_CHARS},
            },
            "required": ["position", "recommendation", "confidence"],
        },
    }


def _candidates(text: str) -> list[tuple[dict[str, JsonValue], str]]:
    """Every JSON object the answer may be, best first, each with the text around it.

    The whole text first, then a fenced block, then the objects in the text from the last one
    back: a model that writes prose and then the object puts the object last.
    """
    decoder = json.JSONDecoder()
    found: list[tuple[dict[str, JsonValue], str]] = []
    stripped = text.strip()
    pieces = [(stripped, "")]
    pieces += [
        (match.group(1).strip(), (text[: match.start()] + text[match.end() :]).strip())
        for match in _FENCE.finditer(text)
    ]
    for piece, rest in pieces:
        try:
            value: JsonValue = json.loads(piece)
        except ValueError:
            continue
        if _is_object(value):
            found.append((value, rest))
    starts = [index for index, char in enumerate(text) if char == "{"]
    # The last objects only: an answer full of braces must not cost a decode per brace.
    for start in reversed(starts[-SEARCH_OBJECTS:]):
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if _is_object(value) and "position" in value:
            found.append((value, (text[:start] + text[end:]).strip()))
    return found


class _Reader:
    """Reads an object field by field and collects every finding instead of stopping at one."""

    def __init__(self, payload: dict[str, JsonValue]) -> None:
        self.payload = payload
        self.findings: list[AnswerFinding] = []

    def add(self, field: str, rule: str, text: str) -> None:
        self.findings.append(finding(field, rule, text))

    def plain(self, field: str, text: str) -> None:
        for rule, phrase in plain_rules(text):
            self.add(field, rule, phrase)

    def choice(self, key: str, allowed: tuple[str, ...]) -> str:
        value = self.payload.get(key)
        folded = value.strip().lower() if isinstance(value, str) else ""
        if folded not in allowed:
            self.add(key, "choice", f"must be one of {', '.join(allowed)}")
        return folded

    def string(self, key: str) -> str | None:
        """The stripped string under ``key``: ``""`` when it is absent, ``None`` (and a finding)
        when it is not a string."""
        value = self.payload.get(key)
        if value is None:
            return ""
        if not isinstance(value, str):
            self.add(key, "type", "must be a string")
            return None
        return value.strip()

    def recommendation(self) -> str:
        text = self.string("recommendation")
        if text is None:
            return ""
        if not text:
            self.add(
                "recommendation",
                "missing",
                f"missing; say in one sentence of at most {RECOMMENDATION_WORDS} words what the "
                "person should do",
            )
            return ""
        words = word_count(text)
        if words > RECOMMENDATION_WORDS:
            self.add("recommendation", "words", f"{words} words; at most {RECOMMENDATION_WORDS}")
        elif len(text) > RECOMMENDATION_CHARS:
            # Twenty very long words: the schema's cap, said in the words a writer can act on.
            self.add(
                "recommendation", "chars", f"{len(text)} characters; at most {RECOMMENDATION_CHARS}"
            )
        sentences = sentence_count(text)
        if sentences > RECOMMENDATION_SENTENCES:
            self.add(
                "recommendation",
                "sentences",
                f"{sentences} sentences; at most {RECOMMENDATION_SENTENCES}",
            )
        self.plain("recommendation", text)
        return text

    def reasoning(self) -> str:
        """The reasoning, checked for its length only: it is the agents' side."""
        text = self.string("reasoning") or ""
        if len(text) > REASONING_CHARS:
            self.add("reasoning", "chars", f"{len(text)} characters; at most {REASONING_CHARS}")
        return text

    def items(self, key: str) -> list[str]:
        value = self.payload.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            self.add(key, "type", "must be a list of strings")
            return []
        # An empty item is dropped, not refused; an item keeps the index its writer gave it.
        listed: list[tuple[int, str]] = []
        for index, entry in enumerate(value):
            if not isinstance(entry, str):
                self.add(key, "type", "must be a list of strings")
                return []
            if entry.strip():
                listed.append((index, entry.strip()))
        if len(listed) > ITEMS:
            self.add(key, "too_many", f"{len(listed)} items; at most {ITEMS}")
        for index, entry in listed:
            path = f"{key}[{index}]"
            if len(entry) > ITEM_CHARS:
                self.add(path, "chars", f"{len(entry)} characters; at most {ITEM_CHARS}")
            self.plain(path, entry)
        return [entry for _, entry in listed]


def read_object(payload: dict[str, JsonValue]) -> tuple[DiscussionAnswer, str]:
    """The answer an object states, and its ``reasoning``; ``AnswerShapeError`` with every finding,
    field by field, when it breaks the standard. Keys outside the standard are ignored."""
    reader = _Reader(payload)
    position = reader.choice("position", POSITIONS)
    recommendation = reader.recommendation()
    lists = {key: reader.items(key) for key in LISTS}
    confidence = reader.choice("confidence", CONFIDENCE)
    reasoning = reader.reasoning()
    if position == "yes" and lists["conditions"]:
        # A yes that names its conditions says yes with conditions; no repair is spent on that.
        position = "yes_with_conditions"
    if position == "yes_with_conditions" and not lists["conditions"]:
        reader.add("conditions", "missing", "missing; yes_with_conditions needs at least one")
    if position == "unclear" and not lists["open_questions"]:
        reader.add("open_questions", "missing", "missing; unclear needs at least one")
    if reader.findings:
        raise AnswerShapeError(reader.findings)
    answer: DiscussionAnswer = {
        "version": VERSION,
        "format": "structured",
        "position": position,
        "recommendation": recommendation,
        "pros": lists["pros"],
        "cons": lists["cons"],
        "conditions": lists["conditions"],
        "open_questions": lists["open_questions"],
        "confidence": confidence,
        "problem": None,
    }
    return answer, reasoning


def parse_answer(text: str) -> tuple[DiscussionAnswer, str]:
    """The structured answer in a provider's text and the prose to store as ``content``.

    The prose is ``reasoning``, else the text around the object, else the recommendation, so a
    message is never empty. ``AnswerShapeError`` carries every finding of the best candidate.
    """
    if len(text) > SEARCH_CHARS:
        raise shape_error("answer", "chars", f"{len(text)} characters; at most {SEARCH_CHARS}")
    candidates = _candidates(text)
    if not candidates:
        raise shape_error("answer", "no_object", "holds no JSON object")
    first: AnswerShapeError | None = None
    for payload, rest in candidates:
        try:
            answer, reasoning = read_object(payload)
        except AnswerShapeError as problem:
            first = first or problem
            continue
        return answer, reasoning or rest or answer["recommendation"]
    raise first or shape_error("answer", "no_object", "holds no JSON object")


def prose_answer(problem: str) -> DiscussionAnswer:
    """An answer that never followed the standard: kept as prose, its position unclear."""
    return {
        "version": VERSION,
        "format": "prose",
        "position": "unclear",
        "recommendation": "",
        "pros": [],
        "cons": [],
        "conditions": [],
        "open_questions": [],
        "confidence": None,
        "problem": problem[:PROBLEM_CHARS],
    }


def _strings(value: JsonValue) -> list[str]:
    return [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []


def _optional(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def read_answer(stored: str) -> DiscussionAnswer | None:
    """A message's stored answer; ``None`` for a person's message or an answer before the
    standard (``{}``), and for anything unreadable. No limit is applied: an answer stored under
    older limits (five items, a long recommendation) reads as it was written."""
    try:
        payload: JsonValue = json.loads(stored or "{}")
    except ValueError:
        return None
    if not _is_object(payload) or payload.get("version") != VERSION:
        return None
    position = payload.get("position")
    shape = payload.get("format")
    recommendation = payload.get("recommendation")
    return {
        "version": VERSION,
        "format": shape if isinstance(shape, str) and shape in FORMATS else "prose",
        "position": position if isinstance(position, str) and position in POSITIONS else "unclear",
        "recommendation": recommendation if isinstance(recommendation, str) else "",
        "pros": _strings(payload.get("pros")),
        "cons": _strings(payload.get("cons")),
        "conditions": _strings(payload.get("conditions")),
        "open_questions": _strings(payload.get("open_questions")),
        "confidence": _optional(payload.get("confidence")),
        "problem": _optional(payload.get("problem")),
    }


def answer_line(answer: DiscussionAnswer | None) -> str:
    """The answer as the next participant's transcript quotes it before the prose."""
    if answer is None:
        return ""
    if answer["format"] == "prose":
        return "(position: unclear; answered in prose only)"
    return f"(position: {answer['position']}; recommendation: {answer['recommendation']})"
