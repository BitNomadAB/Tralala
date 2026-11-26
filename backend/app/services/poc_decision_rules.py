"""The rules of a POC decision and of something missing from a person, all pure.

A POC decision (``kind`` ``decision``) is a choice that can be changed afterwards: the one who works
takes it, records it and goes on. Something missing from a person (``missing``: an API key, an
account) is recorded the same way while the work goes around it. Neither blocks anything; a person
answers each later, with OK or with feedback that becomes a new Ticket.

What a person reads of a record (``POC_PEOPLE_FIELDS``) is held to the plain-text rules every text
for people shares (``plain_text.plain_rules``: no code fence or span, file path or file name, id or
code symbol), the title to ``POC_TITLE_MAX_CHARS`` characters and every other field to
``POC_TEXT_MAX_SENTENCES`` sentences and ``POC_TEXT_MAX_CHARS`` characters. ``details`` is the
text for the AI (files, symbols, evidence) and only bounded in length. Each kind has its required
fields (``POC_REQUIRED``). A breach is ``422 poc_decision_invalid`` whose details name every field
and rule, shaped as ``face_invalid`` is. Nothing here judges text with a model.

The review order, whether a record is due, the counts a Loop summary shows and the feedback Ticket
an answer becomes are computed here from rows, so the service and ``loop_summaries`` agree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypedDict

from ..core.errors import ValidationFailure
from ..db.generated.board import PocDecisionsRow
from ..repositories.poc_decisions import PocDecisionMark
from .loop_identifiers import format_poc_key
from .plain_text import plain_rules, sentence_count
from .plan_views import Readiness, UnplannedTicket

POC_TITLE_MAX_CHARS: Final = 120
POC_TEXT_MAX_SENTENCES: Final = 3
POC_TEXT_MAX_CHARS: Final = 400
POC_DETAILS_MAX_CHARS: Final = 20_000
POC_DECISION_INVALID: Final = "poc_decision_invalid"
POC_DECISION_ANSWERED: Final = "poc_decision_answered"
POC_MAX_ERRORS: Final = 20
"""A refusal lists at most this many messages; the count says how many there were."""

POC_PEOPLE_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "chosen",
    "reason",
    "alternative",
    "change_path",
    "missing",
    "builds_on",
)
"""The fields a person reads, in the order a writer writes them."""

POC_REQUIRED: Final[Mapping[str, tuple[str, ...]]] = {
    "decision": ("title", "chosen", "reason", "alternative", "change_path"),
    "missing": ("title", "missing", "reason", "chosen", "change_path"),
}

# What a missing field asks for, per kind: the sentence a writer reads to fix it.
_ASK: Final[Mapping[str, Mapping[str, str]]] = {
    "decision": {
        "title": "Say in a few words what the decision is about.",
        "chosen": "Say what was chosen.",
        "reason": "Say why it was chosen.",
        "alternative": "Say the alternative that was not chosen.",
        "change_path": "Say how it is changed afterwards.",
    },
    "missing": {
        "title": "Say in a few words what is missing.",
        "missing": "Say what a person has to provide.",
        "reason": "Say why it is needed.",
        "chosen": "Say how the work goes around it.",
        "change_path": "Say what is done once it is there.",
    },
}

# The feedback Ticket a person's feedback becomes is held to the card's own limits.
TICKET_TITLE_MAX_CHARS: Final = 200
TICKET_DESCRIPTION_MAX_CHARS: Final = 20_000


# --- validation ----------------------------------------------------------------------------------


class PocProblemEntry(TypedDict):
    field: str
    rule: str


@dataclass(frozen=True, slots=True)
class PocProblem:
    """One thing a record got wrong: the field, the rule (``missing``, ``chars``, ``sentences``,
    ``code_fence``, ``code_span``, ``file_path``, ``id``, ``finding_id``, ``code_symbol``) and the
    sentence a writer reads."""

    field: str
    rule: str
    message: str

    def entry(self) -> PocProblemEntry:
        return {"field": self.field, "rule": self.rule}


def poc_problems(kind: str, texts: Mapping[str, str]) -> list[PocProblem]:
    """Every problem of a record of ``kind``, field by field in the order a writer writes them;
    ``texts`` holds each field as it was given (absent is empty)."""
    problems: list[PocProblem] = []

    def add(field: str, rule: str, text: str) -> None:
        problems.append(PocProblem(field, rule, f"{field}: {text}"))

    required = POC_REQUIRED.get(kind, ())
    for field in POC_PEOPLE_FIELDS:
        text = texts.get(field, "").strip()
        if not text:
            if field in required:
                add(field, "missing", f"missing. {_ASK[kind][field]}")
            continue
        most = POC_TITLE_MAX_CHARS if field == "title" else POC_TEXT_MAX_CHARS
        if len(text) > most:
            add(field, "chars", f"{len(text)} characters, at most {most}.")
        if field != "title":
            sentences = sentence_count(text)
            if sentences > POC_TEXT_MAX_SENTENCES:
                add(field, "sentences", f"{sentences} sentences, at most {POC_TEXT_MAX_SENTENCES}.")
        for rule, phrase in plain_rules(text):
            add(field, rule, f"{phrase}. Files, symbols and ids belong in details.")
    details = texts.get("details", "")
    if len(details) > POC_DETAILS_MAX_CHARS:
        add("details", "chars", f"{len(details)} characters, at most {POC_DETAILS_MAX_CHARS}.")
    return problems


class PocDecisionRefusal(ValidationFailure):
    """``422 poc_decision_invalid``: every message (at most ``POC_MAX_ERRORS``) in the details'
    ``errors``, the structured problems in ``fields`` and their count; the first five make the
    message."""

    def __init__(self, problems: Sequence[PocProblem]) -> None:
        self.problems = tuple(problems)
        messages = [problem.message for problem in self.problems]
        shown = messages[:POC_MAX_ERRORS]
        super().__init__(
            "The record does not keep its rules: " + " ".join(shown[:5]),
            code=POC_DECISION_INVALID,
            details={
                "errors": shown,
                "error_count": len(messages),
                "fields": [dict(problem.entry()) for problem in self.problems[:POC_MAX_ERRORS]],
            },
        )


def check_record(kind: str, texts: Mapping[str, str]) -> None:
    """Nothing, or ``PocDecisionRefusal`` with every problem."""
    problems = poc_problems(kind, texts)
    if problems:
        raise PocDecisionRefusal(problems)


# --- numbering and the same record again ---------------------------------------------------------


def next_sequence(rows: Iterable[PocDecisionsRow]) -> int:
    """One more than the highest sequence of the Loop's records, so a key is never reused."""
    return max((row.sequence for row in rows), default=0) + 1


def poc_key(loop_key: str, sequence: int) -> str:
    return format_poc_key(loop_key, sequence)


def _same_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def duplicate_of(
    rows: Iterable[PocDecisionsRow], *, kind: str, title: str, chosen: str
) -> PocDecisionsRow | None:
    """The open record of the Loop that says the same (the same kind, title and choice, with
    whitespace and case ignored), so a retried record answers the first one."""
    wanted = (kind, _same_text(title), _same_text(chosen))
    return next(
        (
            row
            for row in rows
            if row.status == "open" and (row.kind, _same_text(row.title), _same_text(row.chosen))
            == wanted
        ),
        None,
    )


# --- review order, due and counts ----------------------------------------------------------------


def mark_of(row: PocDecisionsRow) -> PocDecisionMark:
    return PocDecisionMark(
        loop_id=row.loop_id,
        card_id=row.card_id,
        kind=row.kind,
        status=row.status,
        built_on=row.builds_on != "",
    )


def review_rank(mark: PocDecisionMark) -> int:
    """The group a record is reviewed in: open ones other work builds on first (0), then open
    ones that say what is missing (1), then the other open ones (2), then the answered ones (3)."""
    if mark.status != "open":
        return 3
    if mark.built_on:
        return 0
    if mark.kind == "missing":
        return 1
    return 2


def review_order(rows: Iterable[PocDecisionsRow]) -> list[PocDecisionsRow]:
    """The records in the order a person reviews them: by group, inside a group by sequence."""
    return sorted(rows, key=lambda row: (review_rank(mark_of(row)), row.sequence))


@dataclass(frozen=True, slots=True)
class TicketPhase:
    """The Phase a planned Ticket belongs to: its number and whether it is complete."""

    number: int
    complete: bool


@dataclass(frozen=True, slots=True)
class LoopProgress:
    """What decides whether a record is due: every Ticket of the Loop is completed (and it has at
    least one), and the Phase of each planned Ticket by its card id."""

    all_completed: bool
    phases: Mapping[str, TicketPhase]


def loop_progress(readiness: Readiness, unplanned: Sequence[UnplannedTicket]) -> LoopProgress:
    """The Loop's progress from its readiness: its planned Tickets and the ones added by hand
    (archived ones left out), as the Loop summary counts them."""
    complete = {phase["id"]: phase["state"] == "complete" for phase in readiness["phases"]}
    phases = {
        item["card_id"]: TicketPhase(item["phase_number"], complete.get(item["phase_id"], False))
        for item in readiness["items"]
        if item["card_id"] is not None
    }
    done = [item["completed_at"] is not None for item in readiness["items"]] + [
        ticket["completed_at"] is not None
        for ticket in unplanned
        if ticket["archived_at"] is None
    ]
    return LoopProgress(all_completed=bool(done) and all(done), phases=phases)


def is_due(mark: PocDecisionMark, progress: LoopProgress) -> bool:
    """An open record is due when every Ticket of the Loop is completed, or when other work
    builds on it and the Phase of its Ticket is complete."""
    if mark.status != "open":
        return False
    if progress.all_completed:
        return True
    if not mark.built_on or mark.card_id is None:
        return False
    phase = progress.phases.get(mark.card_id)
    return phase is not None and phase.complete


class PocCounts(TypedDict):
    """A Loop's records as its summary counts them."""

    open: int
    built_on_open: int
    missing_open: int
    due: int
    answered: int


def poc_counts(marks: Iterable[PocDecisionMark], progress: LoopProgress) -> PocCounts:
    counts: PocCounts = {"open": 0, "built_on_open": 0, "missing_open": 0, "due": 0, "answered": 0}
    for mark in marks:
        if mark.status != "open":
            counts["answered"] += 1
            continue
        counts["open"] += 1
        counts["built_on_open"] += int(mark.built_on)
        counts["missing_open"] += int(mark.kind == "missing")
        counts["due"] += int(is_due(mark, progress))
    return counts


# --- the Ticket feedback becomes -----------------------------------------------------------------


def feedback_title(row: PocDecisionsRow) -> str:
    """``Feedback on <key>: <title>``, cut to a Ticket title's limit."""
    title = f"Feedback on {row.key}: {row.title}"
    if len(title) <= TICKET_TITLE_MAX_CHARS:
        return title
    return title[: TICKET_TITLE_MAX_CHARS - 1].rstrip() + "…"


def _labels(kind: str) -> tuple[tuple[str, str], ...]:
    """The fields of the basis, each with the words that introduce it, per kind."""
    if kind == "missing":
        return (
            ("missing", "What a person has to provide"),
            ("reason", "Why it is needed"),
            ("chosen", "How the work went around it"),
            ("change_path", "What is done once it is there"),
            ("alternative", "The alternative"),
            ("builds_on", "What builds on it"),
        )
    return (
        ("chosen", "What was chosen"),
        ("reason", "Why"),
        ("alternative", "The alternative"),
        ("change_path", "How to change it"),
        ("builds_on", "What builds on it"),
    )


def _field(row: PocDecisionsRow, name: str) -> str:
    match name:
        case "missing":
            return row.missing
        case "reason":
            return row.reason
        case "chosen":
            return row.chosen
        case "change_path":
            return row.change_path
        case "alternative":
            return row.alternative
        case _:
            return row.builds_on


def feedback_description(
    row: PocDecisionsRow, feedback: str, ticket: tuple[str | None, str] | None
) -> str:
    """The feedback Ticket's description in Markdown: the person's feedback first, then the
    record it answers as its basis (what was chosen, why, the alternative, how to change it, what
    builds on it, what was missing), the Ticket it was taken on (``ticket``: its key and title)
    and the details, cut so the whole fits a card's description."""
    what = "something missing" if row.kind == "missing" else "a POC decision"
    lines = [
        "## Feedback",
        "",
        feedback,
        "",
        f"## The basis: {what}, {row.key}",
        "",
        f"**{row.title}**",
        "",
    ]
    for name, label in _labels(row.kind):
        value = _field(row, name)
        if value:
            lines.append(f"- {label}: {value}")
    if ticket is not None:
        key, title = ticket
        lines.append(f"- Taken on: {key} {title}" if key else f"- Taken on: {title}")
    text = "\n".join(lines) + "\n"
    if not row.details:
        return text
    heading = "\n### Details\n\n"
    cut_note = f"\n\n(The details are cut here; {row.key} holds them whole.)"
    room = TICKET_DESCRIPTION_MAX_CHARS - len(text) - len(heading)
    if len(row.details) <= room:
        return text + heading + row.details
    kept = max(room - len(cut_note), 0)
    return text + heading + row.details[:kept] + cut_note


__all__ = [
    "POC_DECISION_ANSWERED",
    "POC_DECISION_INVALID",
    "POC_DETAILS_MAX_CHARS",
    "POC_MAX_ERRORS",
    "POC_PEOPLE_FIELDS",
    "POC_REQUIRED",
    "POC_TEXT_MAX_CHARS",
    "POC_TEXT_MAX_SENTENCES",
    "POC_TITLE_MAX_CHARS",
    "TICKET_DESCRIPTION_MAX_CHARS",
    "TICKET_TITLE_MAX_CHARS",
    "LoopProgress",
    "PocCounts",
    "PocDecisionRefusal",
    "PocProblem",
    "PocProblemEntry",
    "TicketPhase",
    "check_record",
    "duplicate_of",
    "feedback_description",
    "feedback_title",
    "is_due",
    "loop_progress",
    "mark_of",
    "next_sequence",
    "poc_counts",
    "poc_key",
    "poc_problems",
    "review_order",
    "review_rank",
]
