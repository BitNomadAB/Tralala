"""The sealed state of a question a key asks its person opens once, for that key and that call."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from app.core.context import ActorContext
from app.core.errors import ValidationFailure
from app.core.secrets import seal_for_purpose
from app.services.request_state import (
    MAX_STATE_CHARS,
    REFUSAL_REASONS,
    REQUEST_STATE_TTL,
    PendingCall,
    RefusalReason,
    RequestStateRefused,
    RequestStateService,
)

SECRET = "request-state-unit-secret-" + "s" * 24
OTHER_SECRET = "another-installation-secret-" + "o" * 24
START = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)

PERSON = "11111111-1111-4111-8111-111111111111"
OTHER_PERSON = "22222222-2222-4222-8222-222222222222"
KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SECOND_KEY = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

CALL = PendingCall(
    "ask_person",
    {
        "decision": "analysis",
        "board_id": "33333333-3333-4333-8333-333333333333",
        "loop_id": "44444444-4444-4444-8444-444444444444",
        "card_id": None,
        "revision_ids": ["55555555-5555-4555-8555-555555555555"],
    },
)


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


def _key(actor_id: str = PERSON, credential_id: str | None = KEY) -> ActorContext:
    return ActorContext(
        actor_id=actor_id, actor_type="agent", actor_name="session", credential_id=credential_id
    )


def _service(clock: Clock | None = None, secret: str = SECRET) -> RequestStateService:
    return RequestStateService(secret, clock=clock or Clock(START))


def _refused(
    service: RequestStateService, actor: ActorContext, call: PendingCall, state: str
) -> RefusalReason:
    with pytest.raises(RequestStateRefused) as refused:
        service.open(actor, call, state)
    return refused.value.reason


def test_a_sealed_state_opens_for_the_key_and_call_that_asked() -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    opened = service.open(_key(), CALL, state)
    assert opened.actor_id == PERSON
    assert opened.credential_id == KEY
    assert opened.tool == "ask_person"
    assert opened.call_digest == CALL.digest()
    assert opened.issued_at == START
    assert opened.expires_at == START + timedelta(minutes=15)
    assert len(opened.nonce) >= 16


def test_the_state_is_valid_for_fifteen_minutes() -> None:
    assert timedelta(minutes=15) == REQUEST_STATE_TTL


def test_the_state_hides_what_it_holds_from_the_client() -> None:
    state = _service().seal(_key(), CALL)
    for visible in (PERSON, KEY, "ask_person", CALL.digest(), "analysis"):
        assert visible not in state
    assert len(state) < MAX_STATE_CHARS


def test_every_state_is_new() -> None:
    service = _service()
    first, second = service.seal(_key(), CALL), service.seal(_key(), CALL)
    assert first != second
    assert service.open(_key(), CALL, first).nonce != service.open(_key(), CALL, second).nonce


@pytest.mark.parametrize("position", [0, 10, 60, 120, -5])
def test_a_changed_byte_is_refused(position: int) -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    index = position % len(state)
    replacement = "B" if state[index] != "B" else "C"
    changed = state[:index] + replacement + state[index + 1 :]
    assert _refused(service, _key(), CALL, changed) == "invalid"
    # The real state still opens: a refused attempt does not use it up.
    assert service.open(_key(), CALL, state).actor_id == PERSON


@pytest.mark.parametrize(
    "state",
    ["", "not-a-state", "gAAAAA", "ä" * 20, "A" * (MAX_STATE_CHARS + 1), "{}"],
)
def test_a_malformed_state_is_refused(state: str) -> None:
    assert _refused(_service(), _key(), CALL, state) == "invalid"


def test_a_state_sealed_with_another_secret_is_refused() -> None:
    state = _service(secret=OTHER_SECRET).seal(_key(), CALL)
    assert _refused(_service(), _key(), CALL, state) == "invalid"


def test_a_value_sealed_for_another_purpose_is_refused() -> None:
    payload = json.dumps({"v": 1, "actor": PERSON}).encode("utf-8")
    state = seal_for_purpose(SECRET, "tralala-something-else-v1", payload)
    assert _refused(_service(), _key(), CALL, state) == "invalid"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"v": 2},
        {"v": 1, "actor": PERSON},
        {
            "v": 1,
            "actor": PERSON,
            "credential": KEY,
            "tool": "ask_person",
            "call": "x",
            "issued": True,
            "expires": 2_000_000_000,
            "nonce": "n",
        },
        {
            "v": 1,
            "actor": PERSON,
            "credential": "",
            "tool": "ask_person",
            "call": "x",
            "issued": 1,
            "expires": 2,
            "nonce": "n",
        },
        {
            "v": 1,
            "actor": PERSON,
            "credential": KEY,
            "tool": "ask_person",
            "call": "x",
            "issued": 5,
            "expires": 5,
            "nonce": "n",
        },
    ],
)
def test_a_sealed_value_that_is_not_a_state_is_refused(payload: object) -> None:
    raw = json.dumps(payload).encode("utf-8")
    state = seal_for_purpose(SECRET, "tralala-request-state-v1", raw)
    assert _refused(_service(), _key(), CALL, state) == "invalid"


def test_an_expired_state_is_refused() -> None:
    clock = Clock(START)
    service = _service(clock)
    state = service.seal(_key(), CALL)
    clock.advance(REQUEST_STATE_TTL)
    assert _refused(service, _key(), CALL, state) == "expired"


def test_a_state_opens_until_its_last_second() -> None:
    clock = Clock(START)
    service = _service(clock)
    state = service.seal(_key(), CALL)
    clock.advance(REQUEST_STATE_TTL - timedelta(seconds=1))
    assert service.open(_key(), CALL, state).actor_id == PERSON


def test_another_actor_is_refused() -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    assert _refused(service, _key(actor_id=OTHER_PERSON), CALL, state) == "wrong_actor"


def test_another_key_of_the_same_person_is_refused() -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    assert _refused(service, _key(credential_id=SECOND_KEY), CALL, state) == "wrong_credential"
    assert _refused(service, _key(credential_id=None), CALL, state) == "wrong_credential"


def test_a_state_from_a_session_without_a_key_does_not_open_for_a_key() -> None:
    service = _service()
    state = service.seal(_key(credential_id=None), CALL)
    assert _refused(service, _key(), CALL, state) == "wrong_credential"
    assert service.open(_key(credential_id=None), CALL, state).credential_id is None


def test_a_person_with_several_keys_gets_one_state_per_key() -> None:
    service = _service()
    first = service.seal(_key(credential_id=KEY), CALL)
    second = service.seal(_key(credential_id=SECOND_KEY), CALL)
    assert _refused(service, _key(credential_id=SECOND_KEY), CALL, first) == "wrong_credential"
    assert _refused(service, _key(credential_id=KEY), CALL, second) == "wrong_credential"
    assert service.open(_key(credential_id=KEY), CALL, first).credential_id == KEY
    assert service.open(_key(credential_id=SECOND_KEY), CALL, second).credential_id == SECOND_KEY


@pytest.mark.parametrize(
    "other",
    [
        PendingCall("another_tool", CALL.arguments),
        PendingCall("ask_person", {**CALL.arguments, "decision": "roadmap"}),
        PendingCall("ask_person", {**CALL.arguments, "card_id": KEY}),
        PendingCall(
            "ask_person",
            {**CALL.arguments, "revision_ids": ["66666666-6666-4666-8666-666666666666"]},
        ),
        PendingCall("ask_person", {k: v for k, v in CALL.arguments.items() if k != "card_id"}),
    ],
)
def test_another_call_is_refused(other: PendingCall) -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    assert _refused(service, _key(), other, state) == "wrong_call"


def test_the_call_hash_does_not_depend_on_the_order_of_the_arguments() -> None:
    reordered = PendingCall("ask_person", dict(reversed(list(CALL.arguments.items()))))
    assert reordered.digest() == CALL.digest()
    service = _service()
    assert service.open(_key(), reordered, service.seal(_key(), CALL)).tool == "ask_person"


def test_a_used_state_is_refused() -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    service.open(_key(), CALL, state)
    assert _refused(service, _key(), CALL, state) == "reused"


def test_a_refused_attempt_does_not_use_the_state_up() -> None:
    service = _service()
    state = service.seal(_key(), CALL)
    assert _refused(service, _key(actor_id=OTHER_PERSON), CALL, state) == "wrong_actor"
    assert service.open(_key(), CALL, state).actor_id == PERSON


def test_used_states_are_forgotten_once_they_have_expired() -> None:
    clock = Clock(START)
    service = _service(clock)
    first = service.seal(_key(), CALL)
    service.open(_key(), CALL, first)
    clock.advance(timedelta(minutes=5))
    second = service.seal(_key(), CALL)
    service.open(_key(), CALL, second)
    assert service.remembered() == 2
    clock.advance(REQUEST_STATE_TTL - timedelta(minutes=5))
    # The first state has expired: the next seal forgets it, and it is refused as expired.
    service.seal(_key(), CALL)
    assert service.remembered() == 1
    assert _refused(service, _key(), CALL, first) == "expired"
    clock.advance(timedelta(minutes=5))
    assert _refused(service, _key(), CALL, second) == "expired"
    service.seal(_key(), CALL)
    assert service.remembered() == 0


def test_an_expired_state_is_refused_as_expired_before_anything_else() -> None:
    clock = Clock(START)
    service = _service(clock)
    state = service.seal(_key(), CALL)
    clock.advance(REQUEST_STATE_TTL)
    assert _refused(service, _key(actor_id=OTHER_PERSON), CALL, state) == "expired"


def test_a_restarted_process_forgets_used_states_until_they_expire() -> None:
    clock = Clock(START)
    state = _service(clock).seal(_key(), CALL)
    before_restart = _service(clock)
    before_restart.open(_key(), CALL, state)
    after_restart = _service(clock)
    assert after_restart.open(_key(), CALL, state).actor_id == PERSON
    clock.advance(REQUEST_STATE_TTL)
    assert _refused(_service(clock), _key(), CALL, state) == "expired"


def test_a_refusal_is_a_validation_failure_that_names_only_the_reason() -> None:
    refusal = RequestStateRefused("reused")
    assert isinstance(refusal, ValidationFailure)
    assert refusal.code == "request_state_refused"
    assert refusal.status_code == 422
    assert refusal.details == {"reason": "reused"}
    assert set(REFUSAL_REASONS) == {
        "invalid",
        "expired",
        "wrong_actor",
        "wrong_credential",
        "wrong_call",
        "reused",
    }


def test_the_service_needs_a_secret() -> None:
    with pytest.raises(ValueError, match="secret"):
        RequestStateService("", clock=Clock(START))


SUBJECT: dict[str, JsonValue] = {"revisions": {"analysis": "77777777-7777-4777-8777-777777777777"}}


def test_the_subject_comes_back_sealed_and_hashed_with_the_call() -> None:
    service = _service()
    state = service.seal(_key(), CALL, SUBJECT)
    assert "77777777" not in state
    opened = service.open(_key(), CALL, state)
    assert opened.subject == SUBJECT
    assert opened.call_digest == CALL.digest(SUBJECT)
    assert CALL.digest(SUBJECT) != CALL.digest()


def test_a_state_without_a_subject_opens_with_an_empty_one() -> None:
    service = _service()
    assert service.open(_key(), CALL, service.seal(_key(), CALL)).subject == {}


def test_a_sealed_subject_that_is_not_an_object_is_refused() -> None:
    payload = {
        "v": 1,
        "actor": PERSON,
        "credential": KEY,
        "tool": "ask_person",
        "call": CALL.digest(),
        "issued": 2_000_000_000,
        "expires": 2_000_000_900,
        "nonce": "n",
        "subject": ["not", "an", "object"],
    }
    state = seal_for_purpose(SECRET, "tralala-request-state-v1", json.dumps(payload).encode())
    assert _refused(_service(), _key(), CALL, state) == "invalid"
