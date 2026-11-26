"""POC decisions, what is missing from a person, and a Loop's stop list at the REST boundary.

The request models only bound what a request may carry; the limits a person reads by
(``services/poc_decision_rules.py``) are the service's, so a breach names each field and rule
(``422 poc_decision_invalid``) instead of failing as a generic validation error.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, StringConstraints, model_validator

from .common import Id, OutModel, StrictModel

PocKind = Literal["decision", "missing"]
POC_KINDS: tuple[str, ...] = get_args(PocKind)
PocStatus = Literal["open", "ok", "feedback"]
POC_STATUSES: tuple[str, ...] = get_args(PocStatus)
PocAnswerKind = Literal["ok", "feedback"]

POC_INPUT_MAX_CHARS = 4000
"""The most a people-facing field may carry in a request; the service holds it to far less."""
POC_DETAILS_INPUT_MAX_CHARS = 40_000
"""The most ``details`` may carry in a request; the service holds it to 20,000 characters."""
POC_FEEDBACK_MAX_CHARS = 2000
"""A person's feedback holds 1 to this many characters, as ``ck_poc_decisions_feedback_length``
stores it."""

PocText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=POC_INPUT_MAX_CHARS)]
PocDetails = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=POC_DETAILS_INPUT_MAX_CHARS)
]
PocFeedback = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=POC_FEEDBACK_MAX_CHARS)
]
STOPS_INPUT_MAX_LINES = 50
STOP_INPUT_MAX_CHARS = 1000


class PocDecisionCreate(StrictModel):
    """A POC decision (``kind`` ``decision``) or something missing from a person (``missing``).

    ``decision`` needs ``title``, ``chosen``, ``reason``, ``alternative`` and ``change_path``;
    ``missing`` needs ``title``, ``missing``, ``reason``, ``chosen`` and ``change_path``."""

    kind: PocKind
    card_id: Id | None = Field(default=None, description="The Ticket it was taken on, if any")
    title: PocText = Field(default="", description="What it is about, at most 120 characters")
    chosen: PocText = Field(
        default="", description="What was chosen; for missing, how the work goes around it"
    )
    reason: PocText = Field(default="", description="Why; for missing, why it is needed")
    alternative: PocText = Field(default="", description="The alternative that was not chosen")
    change_path: PocText = Field(
        default="",
        description="How it is changed afterwards; for missing, what is done once it is there",
    )
    missing: PocText = Field(default="", description="For missing: what a person has to provide")
    builds_on: PocText = Field(
        default="", description="What other work builds on it; empty when nothing does"
    )
    details: PocDetails = Field(
        default="", description="Text for the AI: files, symbols, evidence (20,000 characters)"
    )


class PocDecisionAnswerCreate(StrictModel):
    """A person's answer: ``ok``, or ``feedback`` with 1 to 2,000 characters of it."""

    answer: PocAnswerKind
    feedback: PocFeedback = ""

    @model_validator(mode="after")
    def _feedback(self) -> Self:
        if self.answer == "feedback" and not self.feedback:
            raise ValueError("feedback is required when the answer is feedback")
        if self.answer == "ok" and self.feedback:
            raise ValueError("feedback is only given with the answer feedback")
        return self


class StopListUpdate(StrictModel):
    """The Loop's whole stop list: 0 to 12 lines; an empty list means nothing stops."""

    stops: list[Annotated[str, StringConstraints(max_length=STOP_INPUT_MAX_CHARS)]] = Field(
        max_length=STOPS_INPUT_MAX_LINES
    )


class PocActorOut(OutModel):
    name: str
    type: str


class PocTicketRefOut(OutModel):
    id: str
    key: str | None


class PocDecisionOut(OutModel):
    id: str
    key: str
    loop_id: str
    card_id: str | None
    ticket_key: str | None
    ticket_title: str | None
    phase_number: int | None
    phase_complete: bool | None
    kind: PocKind
    title: str
    chosen: str
    reason: str
    alternative: str
    change_path: str
    missing: str
    builds_on: str
    built_on: bool
    details: str
    status: PocStatus
    feedback: str
    feedback_ticket: PocTicketRefOut | None
    due: bool = Field(
        description=(
            "Open, and every Ticket of the Loop is completed, or other work builds on it and "
            "the Phase of its Ticket is complete"
        )
    )
    created_at: str
    created_by: PocActorOut
    answered_at: str | None
    answered_by_name: str | None


class PocDecisionRecordedOut(PocDecisionOut):
    deduplicated: bool = Field(
        description="True when the same open record already existed and is answered instead"
    )


class PocCountsOut(OutModel):
    open: int
    built_on_open: int
    missing_open: int
    due: int
    answered: int


class PocDecisionListOut(OutModel):
    items: list[PocDecisionOut]
    counts: PocCountsOut


class StopListOut(OutModel):
    stops: list[str]
    is_default: bool


__all__ = [
    "POC_DETAILS_INPUT_MAX_CHARS",
    "POC_FEEDBACK_MAX_CHARS",
    "POC_INPUT_MAX_CHARS",
    "POC_KINDS",
    "POC_STATUSES",
    "PocActorOut",
    "PocAnswerKind",
    "PocCountsOut",
    "PocDecisionAnswerCreate",
    "PocDecisionCreate",
    "PocDecisionListOut",
    "PocDecisionOut",
    "PocDecisionRecordedOut",
    "PocKind",
    "PocStatus",
    "PocTicketRefOut",
    "StopListOut",
    "StopListUpdate",
]
