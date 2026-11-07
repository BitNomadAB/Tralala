"""The standard a discussion answer follows: its fields, the prompt that asks for it, the schema a
provider may enforce, and the parser that reads it from an untrusted answer.

A participant answers a round with one JSON object (``DiscussionAnswer``, version 1): a position
from the analysis brief's verdict set, a one-sentence recommendation, reasons for and against, the
conditions of a yes, the questions it could not settle, and its confidence. The prose
(``reasoning``, or the text around the object) stays the message's ``content``; the structure is
stored beside it as ``answer_json``. An answer that never follows the shape is kept as prose with
the position ``unclear`` (``prose_answer``), never dropped.
"""

from __future__ import annotations

import json
import re
from typing import TypedDict, TypeIs

from pydantic import JsonValue

from .runtime import ResponseSchema

VERSION = 1
POSITIONS = ("yes", "yes_with_conditions", "no", "unclear")
# The positions that support going ahead: consensus is every participant on this side.
GO = frozenset({"yes", "yes_with_conditions"})
CONFIDENCE = ("high", "medium", "low")
FORMATS = ("structured", "repaired", "prose")
LISTS = ("pros", "cons", "conditions", "open_questions")

RECOMMENDATION_CHARS = 300
ITEM_CHARS = 200
ITEMS = 5
REASONING_CHARS = 8000
PROBLEM_CHARS = 300
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


class AnswerShapeError(ValueError):
    """The answer does not follow the standard; the message says what to fix."""


def _is_object(value: JsonValue) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def answer_instructions() -> str:
    """The last section of a round's prompt: how to answer."""
    return (
        "Answer with one JSON object and nothing else:\n"
        "{\n"
        '  "position": "yes" | "yes_with_conditions" | "no" | "unclear",\n'
        f'  "recommendation": "one sentence: what the person should do (at most '
        f'{RECOMMENDATION_CHARS} characters)",\n'
        '  "pros": ["for going ahead"],\n'
        '  "cons": ["against, and the risks"],\n'
        '  "conditions": ["what must hold; at least one when yes_with_conditions"],\n'
        '  "open_questions": ["what you cannot settle; at least one when unclear"],\n'
        '  "confidence": "high" | "medium" | "low",\n'
        '  "reasoning": "your analysis from your role, in Markdown; name the participant you '
        'are answering"\n'
        "}\n"
        "`position` answers whether the person should go ahead with what the discussion goal "
        f"proposes. Each list holds at most {ITEMS} short items of at most {ITEM_CHARS} "
        "characters; leave a list empty rather than repeat yourself. A person decides; you "
        "advise."
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


def _text_field(payload: dict[str, JsonValue], key: str, limit: int, *, required: bool) -> str:
    value = payload.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise AnswerShapeError(f"`{key}` must be a string")
    value = value.strip()
    if required and not value:
        raise AnswerShapeError(f"`{key}` must not be empty")
    if len(value) > limit:
        raise AnswerShapeError(f"`{key}` has {len(value)} characters; at most {limit}")
    return value


def _list_field(payload: dict[str, JsonValue], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnswerShapeError(f"`{key}` must be a list of strings")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise AnswerShapeError(f"`{key}` must be a list of strings")
        if entry.strip():
            items.append(entry.strip())
    if len(items) > ITEMS:
        raise AnswerShapeError(f"`{key}` has {len(items)} items; at most {ITEMS}")
    for entry in items:
        if len(entry) > ITEM_CHARS:
            raise AnswerShapeError(
                f"an item of `{key}` has {len(entry)} characters; at most {ITEM_CHARS}"
            )
    return items


def _choice(payload: dict[str, JsonValue], key: str, allowed: tuple[str, ...]) -> str:
    value = payload.get(key)
    folded = value.strip().lower() if isinstance(value, str) else ""
    if folded not in allowed:
        raise AnswerShapeError(f"`{key}` must be one of {', '.join(allowed)}")
    return folded


def read_object(payload: dict[str, JsonValue]) -> tuple[DiscussionAnswer, str]:
    """The answer an object states, and its ``reasoning``; ``AnswerShapeError`` when it breaks the
    standard. Keys outside the standard are ignored."""
    position = _choice(payload, "position", POSITIONS)
    lists = {key: _list_field(payload, key) for key in LISTS}
    if position == "yes" and lists["conditions"]:
        # A yes that names its conditions says yes with conditions; no repair is spent on that.
        position = "yes_with_conditions"
    if position == "yes_with_conditions" and not lists["conditions"]:
        raise AnswerShapeError("`yes_with_conditions` needs at least one item in `conditions`")
    if position == "unclear" and not lists["open_questions"]:
        raise AnswerShapeError("`unclear` needs at least one item in `open_questions`")
    answer: DiscussionAnswer = {
        "version": VERSION,
        "format": "structured",
        "position": position,
        "recommendation": _text_field(
            payload, "recommendation", RECOMMENDATION_CHARS, required=True
        ),
        "pros": lists["pros"],
        "cons": lists["cons"],
        "conditions": lists["conditions"],
        "open_questions": lists["open_questions"],
        "confidence": _choice(payload, "confidence", CONFIDENCE),
        "problem": None,
    }
    reasoning = _text_field(payload, "reasoning", REASONING_CHARS, required=False)
    return answer, reasoning


def parse_answer(text: str) -> tuple[DiscussionAnswer, str]:
    """The structured answer in a provider's text and the prose to store as ``content``.

    The prose is ``reasoning``, else the text around the object, else the recommendation, so a
    message is never empty. ``AnswerShapeError`` names the first rule the best candidate broke.
    """
    if len(text) > SEARCH_CHARS:
        raise AnswerShapeError(f"the answer has {len(text)} characters; at most {SEARCH_CHARS}")
    candidates = _candidates(text)
    if not candidates:
        raise AnswerShapeError("the answer holds no JSON object")
    first: AnswerShapeError | None = None
    for payload, rest in candidates:
        try:
            answer, reasoning = read_object(payload)
        except AnswerShapeError as problem:
            first = first or problem
            continue
        return answer, reasoning or rest or answer["recommendation"]
    raise first or AnswerShapeError("the answer holds no JSON object")


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
    standard (``{}``), and for anything unreadable."""
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
