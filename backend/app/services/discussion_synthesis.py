"""Decision support after a round: what the participants' latest answers say, side by side.

Tralala computes the synthesis; no model writes it. It repeats only what named participants said
(who is for going ahead and who is against, with each one's recommendation; the conditions of a yes;
the open questions; who has not answered), and it suggests a verdict by fixed rules, with a reason
of one sentence of at most twenty words that names nobody. It is labelled decision support and its
verdict a suggestion: the person decides (rule 11a).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TypedDict, TypeIs

from pydantic import JsonValue

from ..db.generated.board import DiscussionMessagesRow, DiscussionParticipantsRow
from .discussion_answers import GO, POSITIONS, DiscussionAnswer, read_answer

VERSION = 1
LIST_LIMIT = 20


class Stance(TypedDict):
    """One participant's latest answer as the synthesis lists it."""

    participant_id: str
    participant: str
    position: str
    recommendation: str
    confidence: str | None
    format: str
    message_id: str
    round_number: int


class Point(TypedDict):
    """A condition or an open question, with the participants who named it."""

    text: str
    participants: list[str]


class Suggestion(TypedDict):
    verdict: str
    reason: str


class RoundSynthesis(TypedDict):
    version: int
    kind: str
    written_by: str
    round_number: int
    thread_round: int
    suggestion: Suggestion
    counts: dict[str, int]
    go: list[Stance]
    stop: list[Stance]
    unclear: list[Stance]
    conditions: list[Point]
    open_questions: list[Point]
    missing: list[str]


type Latest = Mapping[str, tuple[DiscussionMessagesRow, DiscussionAnswer]]
"""Each participant's latest structured answer, by participant id."""


def latest_answers(
    messages: Sequence[DiscussionMessagesRow], participants: Sequence[DiscussionParticipantsRow]
) -> dict[str, tuple[DiscussionMessagesRow, DiscussionAnswer]]:
    """Each participant's latest answer in the standard, from the thread's messages oldest first.

    A message before the standard (``answer_json`` ``{}``) is skipped, so a participant who only
    answered before it reads as missing rather than as a position nobody stated.
    """
    ids = {participant.participant_id for participant in participants}
    latest: dict[str, tuple[DiscussionMessagesRow, DiscussionAnswer]] = {}
    for message in messages:
        if message.author_type != "agent" or message.author_actor_id not in ids:
            continue
        answer = read_answer(message.answer_json)
        if answer is not None:
            latest[message.author_actor_id] = (message, answer)
    return latest


def _stance(
    participant: DiscussionParticipantsRow, message: DiscussionMessagesRow, answer: DiscussionAnswer
) -> Stance:
    return {
        "participant_id": participant.participant_id,
        "participant": participant.display_name,
        "position": answer["position"],
        "recommendation": answer["recommendation"],
        "confidence": answer["confidence"],
        "format": answer["format"],
        "message_id": message.id,
        "round_number": message.round_number,
    }


def positions(participants: Sequence[DiscussionParticipantsRow], latest: Latest) -> list[Stance]:
    """Each participant's current position in the order they joined: the vote list a person
    sees."""
    return [
        _stance(participant, *latest[participant.participant_id])
        for participant in participants
        if participant.participant_id in latest
    ]


def _points(entries: list[tuple[str, str]]) -> list[Point]:
    """Texts with the participants who named them; the same text twice is one point."""
    points: dict[str, Point] = {}
    for participant, text in entries:
        key = " ".join(text.casefold().split())
        point = points.setdefault(key, {"text": text, "participants": []})
        if participant not in point["participants"]:
            point["participants"].append(participant)
    return list(points.values())[:LIST_LIMIT]


def _counted(go: int, stop: int, unclear: int, missing: int) -> str:
    """How many stand where, in one clause: ``1 for going ahead, 1 against and 2 cannot tell``."""
    parts: list[str] = []
    if go:
        parts.append(f"{go} for going ahead")
    if stop:
        parts.append(f"{stop} against")
    if unclear:
        parts.append(f"{unclear} cannot tell")
    if missing:
        parts.append(f"{missing} {'has' if missing == 1 else 'have'} not answered")
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def suggest(
    go: list[Stance], stop: list[Stance], unclear: list[Stance], missing: list[str]
) -> Suggestion:
    """The verdict the answers point to, by fixed rules, with the reason; never a decision.

    The reason is the sign's sentence: one sentence of at most ``RECOMMENDATION_WORDS`` words on
    every branch. It counts who stands where and names nobody; who cannot tell and who is missing
    are shown from ``unclear`` and ``missing``."""
    if not go and not stop and not unclear:
        return {"verdict": "unclear", "reason": "Nobody has answered in the standard form yet."}
    if go and not stop and not unclear and not missing:
        conditions = sum(1 for stance in go if stance["position"] == "yes_with_conditions")
        if not conditions:
            return {"verdict": "yes", "reason": "Every participant supports going ahead."}
        return {
            "verdict": "yes_with_conditions",
            "reason": "Every participant supports going ahead; read the conditions before you do.",
        }
    if stop and not go and not unclear and not missing:
        return {"verdict": "no", "reason": "Every participant advises against going ahead."}
    split = bool(go and stop)
    lead = "The participants differ" if split else "Not settled yet"
    counted = _counted(len(go), len(stop), len(unclear), len(missing))
    # A split already fills the sentence; the hint to the open questions fits only without one.
    tail = "; read the open questions" if unclear and not split else ""
    return {"verdict": "unclear", "reason": f"{lead}: {counted}{tail}."}


def synthesize(
    participants: Sequence[DiscussionParticipantsRow],
    latest: Latest,
    *,
    round_number: int,
    thread_round: int,
) -> RoundSynthesis:
    """The decision support for the thread as it stands after a round."""
    go: list[Stance] = []
    stop: list[Stance] = []
    unclear: list[Stance] = []
    missing: list[str] = []
    conditions: list[tuple[str, str]] = []
    questions: list[tuple[str, str]] = []
    counts: dict[str, int] = dict.fromkeys(POSITIONS, 0)
    for participant in participants:
        found = latest.get(participant.participant_id)
        if found is None:
            missing.append(participant.display_name)
            continue
        message, answer = found
        stance = _stance(participant, message, answer)
        counts[answer["position"]] = counts.get(answer["position"], 0) + 1
        if answer["position"] in GO:
            go.append(stance)
        elif answer["position"] == "no":
            stop.append(stance)
        else:
            unclear.append(stance)
        conditions += [(participant.display_name, text) for text in answer["conditions"]]
        questions += [(participant.display_name, text) for text in answer["open_questions"]]
    counts["missing"] = len(missing)
    return {
        "version": VERSION,
        "kind": "decision_support",
        "written_by": "tralala",
        "round_number": round_number,
        "thread_round": thread_round,
        "suggestion": suggest(go, stop, unclear, missing),
        "counts": counts,
        "go": go,
        "stop": stop,
        "unclear": unclear,
        "conditions": _points(conditions),
        "open_questions": _points(questions),
        "missing": missing,
    }


def _is_object(value: JsonValue) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def read_synthesis(stored: str) -> dict[str, JsonValue] | None:
    """A round's stored synthesis as JSON; ``None`` for a round before it (``{}``) or anything
    unreadable. The API answers it as stored: Tralala wrote it, in this module's shape."""
    try:
        payload: JsonValue = json.loads(stored or "{}")
    except ValueError:
        return None
    if not _is_object(payload) or payload.get("version") != VERSION:
        return None
    return payload
