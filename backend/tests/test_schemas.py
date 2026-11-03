"""The request boundary: unknown fields, free-text dates and unknown scopes never get through."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import app.schemas
from app.schemas.auth import CredentialCreate, LoginRequest
from app.schemas.boards import BoardCreate
from app.schemas.cards import CardCreate, CardUpdate
from app.schemas.common import OutModel, StrictModel
from app.schemas.loops import AnalysisPayload, GenerationRequest, QaInstructions

# Response shapes that are neither requests nor `OutModel`s; nothing parses a request with them.
RESPONSE_SHAPES = {"OrmModel", "Page", "Envelope", "ErrorBody", "ErrorEnvelope"}


def _schema_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for module_info in pkgutil.iter_modules(app.schemas.__path__):
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for value in vars(module).values():
            if (
                inspect.isclass(value)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
            ):
                models.append(value)
    return models


def _errors(model: type[BaseModel], payload: dict[str, Any]) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as failure:
        model.model_validate(payload)
    return list(failure.value.errors())


def test_every_request_model_rejects_unknown_fields() -> None:
    strict = [model for model in _schema_models() if issubclass(model, StrictModel)]
    assert strict, "no request models found"
    lenient = [model.__name__ for model in strict if model.model_config.get("extra") != "forbid"]
    assert lenient == []


def test_every_schema_model_is_a_request_or_a_response() -> None:
    """A model that is neither would accept unknown fields if a route ever parsed a body with it."""
    unclassified = [
        model.__name__
        for model in _schema_models()
        if not issubclass(model, StrictModel | OutModel) and model.__name__ not in RESPONSE_SHAPES
    ]
    assert unclassified == []


def test_an_unknown_field_is_named_in_the_error() -> None:
    errors = _errors(BoardCreate, {"name": "Board", "unexpected": True})
    assert [(error["type"], error["loc"]) for error in errors] == [
        ("extra_forbidden", ("unexpected",))
    ]


@pytest.mark.parametrize("value", ["next tuesday", "2026-13-45", "15/01/2027"])
def test_a_ticket_due_date_must_be_iso_8601(value: str) -> None:
    errors = _errors(CardCreate, {"list_id": "l1", "title": "Ticket", "due_at": value})
    assert [error["loc"] for error in errors] == [("due_at",)]
    errors = _errors(CardUpdate, {"version": 1, "due_at": value})
    assert [error["loc"] for error in errors] == [("due_at",)]


def test_a_ticket_due_date_is_stored_as_utc() -> None:
    created = CardCreate(list_id="l1", title="Ticket", due_at="2027-01-15")
    assert created.due_at == "2027-01-15T00:00:00Z"
    updated = CardUpdate(version=3, due_at="2027-01-15T10:30:00+02:00")
    assert updated.due_at == "2027-01-15T08:30:00Z"


def test_an_update_needs_the_version_it_expects() -> None:
    errors = _errors(CardUpdate, {"title": "Renamed"})
    assert [(error["type"], error["loc"]) for error in errors] == [("missing", ("version",))]
    assert [error["loc"] for error in _errors(CardUpdate, {"version": 0})] == [("version",)]


def test_a_sign_in_trims_the_name_but_never_the_password() -> None:
    login = LoginRequest(username="  admin  ", password="  spaced  ")
    assert login.username == "admin"
    assert login.password == "  spaced  "
    blank = _errors(LoginRequest, {"username": " ", "password": "x"})
    assert [error["loc"] for error in blank] == [("username",)]


@pytest.mark.parametrize(
    "scope", ["users:admin", "credentials:admin", "agents:admin", "loops:review", "everything"]
)
def test_a_token_cannot_be_issued_with_an_ungrantable_scope(scope: str) -> None:
    errors = _errors(CredentialCreate, {"name": "worker", "scopes": ["boards:read", scope]})
    assert [error["loc"] for error in errors] == [("scopes", 1)]


def test_a_token_needs_at_least_one_scope() -> None:
    errors = _errors(CredentialCreate, {"name": "worker", "scopes": []})
    assert [error["loc"] for error in errors] == [("scopes",)]


def test_a_generation_names_a_known_purpose() -> None:
    assert GenerationRequest(purpose="analysis").purpose == "analysis"
    assert [error["loc"] for error in _errors(GenerationRequest, {"purpose": "deploy"})] == [
        ("purpose",)
    ]


def _finding(identifier: str) -> dict[str, str]:
    return {
        "id": identifier,
        "title": "Nothing exists",
        "category": "change",
        "technical_detail": "detail",
        "plain_language": "This must be built from scratch.",
    }


def test_an_analysis_cannot_repeat_a_finding_id() -> None:
    payload = {"outcome": "Verify email", "findings": [_finding("F-01"), _finding("F-01")]}
    errors = _errors(AnalysisPayload, payload)
    assert [error["loc"] for error in errors] == [("findings",)]
    assert "duplicate finding id: F-01" in errors[0]["msg"]


def _scenario(identifier: str, steps_human: list[str]) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": "Sign in",
        "kind": "happy_path",
        "steps_ai": ["POST /auth/login"],
        "steps_human": steps_human,
        "expected_result": "Signed in",
    }


def test_qa_instructions_need_human_steps_and_unique_ids() -> None:
    QaInstructions.model_validate({"scenarios": [_scenario("S-1", ["1. Open the page"])]})
    without_steps = _errors(QaInstructions, {"scenarios": [_scenario("S-1", [])]})
    assert [error["loc"] for error in without_steps] == [("scenarios", 0, "steps_human")]
    twice = _errors(
        QaInstructions,
        {"scenarios": [_scenario("S-1", ["1. Open"]), _scenario("S-1", ["1. Open"])]},
    )
    assert "duplicate scenario id: S-1" in twice[0]["msg"]
