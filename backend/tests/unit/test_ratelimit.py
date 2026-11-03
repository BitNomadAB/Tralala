"""Rate limiting and sign-in throttling, against a clock the test moves by hand."""

from __future__ import annotations

from contextlib import ExitStack

import pytest

from app.core import ratelimit
from app.core.errors import RateLimited
from app.core.ratelimit import LoginThrottle, RateLimiter


class Clock:
    """Stands in for the `time` module: `monotonic()` returns what the test set."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(ratelimit, "time", fake)
    return fake


@pytest.mark.usefixtures("clock")
def test_the_limit_holds_per_actor_within_the_window() -> None:
    limiter = RateLimiter(3)
    for _ in range(3):
        limiter.check("actor-a")
    with pytest.raises(RateLimited) as refused:
        limiter.check("actor-a")
    assert refused.value.status_code == 429
    assert refused.value.retryable is True
    assert refused.value.details == {"limit": 3, "window_seconds": 60}
    limiter.check("actor-b")


def test_the_window_slides(clock: Clock) -> None:
    limiter = RateLimiter(2)
    limiter.check("actor-a")
    clock.now += 30
    limiter.check("actor-a")
    clock.now += 31
    limiter.check("actor-a")
    with pytest.raises(RateLimited):
        limiter.check("actor-a")


@pytest.mark.usefixtures("clock")
def test_a_limit_of_zero_disables_the_limiter() -> None:
    limiter = RateLimiter(0)
    for _ in range(1000):
        limiter.check("actor-a")


def test_sign_in_is_locked_after_repeated_failures(clock: Clock) -> None:
    throttle = LoginThrottle(max_failures=3, base_seconds=30, max_seconds=100)
    for _ in range(2):
        throttle.record_failure("user:alice", "ip:192.168.1.10")
    throttle.check("user:alice", "ip:192.168.1.10")

    throttle.record_failure("user:alice", "ip:192.168.1.10")
    with pytest.raises(RateLimited) as refused:
        throttle.check("user:alice")
    assert refused.value.details == {"retry_after_seconds": 31}
    with pytest.raises(RateLimited):
        throttle.check("user:bob", "ip:192.168.1.10")
    throttle.check("user:bob", "ip:192.168.1.11")

    clock.now += 30
    throttle.check("user:alice")


@pytest.mark.usefixtures("clock")
def test_the_lock_doubles_and_stops_at_the_ceiling() -> None:
    throttle = LoginThrottle(max_failures=1, base_seconds=30, max_seconds=100)
    waits: list[object] = []
    for _ in range(4):
        throttle.record_failure("user:alice")
        with pytest.raises(RateLimited) as refused:
            throttle.check("user:alice")
        assert refused.value.details is not None
        waits.append(refused.value.details["retry_after_seconds"])
    assert waits == [31, 61, 101, 101]


@pytest.mark.usefixtures("clock")
def test_a_successful_sign_in_clears_the_record() -> None:
    throttle = LoginThrottle(max_failures=1, base_seconds=30, max_seconds=100)
    throttle.record_failure("user:alice")
    throttle.reset("user:alice")
    throttle.check("user:alice")


@pytest.mark.usefixtures("clock")
def test_parallel_attempts_are_capped_at_the_failures_left() -> None:
    throttle = LoginThrottle(max_failures=3, base_seconds=30, max_seconds=100)
    with ExitStack() as running:
        for _ in range(3):
            running.enter_context(throttle.attempt("user:alice", "ip:192.168.1.10"))
        with pytest.raises(RateLimited) as refused:
            running.enter_context(throttle.attempt("user:alice", "ip:192.168.1.11"))
        assert refused.value.details == {"retry_after_seconds": 1}
        with pytest.raises(RateLimited):
            running.enter_context(throttle.attempt("user:bob", "ip:192.168.1.10"))
        running.enter_context(throttle.attempt("user:bob", "ip:192.168.1.11"))
    with throttle.attempt("user:alice", "ip:192.168.1.10"):
        throttle.record_failure("user:alice", "ip:192.168.1.10")
    with ExitStack() as running:
        for _ in range(2):
            running.enter_context(throttle.attempt("user:alice"))
        with pytest.raises(RateLimited):
            running.enter_context(throttle.attempt("user:alice"))


def test_a_key_at_the_limit_admits_one_attempt_at_a_time(clock: Clock) -> None:
    throttle = LoginThrottle(max_failures=2, base_seconds=30, max_seconds=100)
    for _ in range(2):
        with throttle.attempt("user:alice"):
            throttle.record_failure("user:alice")
    with ExitStack() as running:
        with pytest.raises(RateLimited) as refused:
            running.enter_context(throttle.attempt("user:alice"))
        assert refused.value.details == {"retry_after_seconds": 31}

        clock.now += 30
        running.enter_context(throttle.attempt("user:alice"))
        with pytest.raises(RateLimited):
            running.enter_context(throttle.attempt("user:alice"))


@pytest.mark.usefixtures("clock")
def test_an_attempt_is_released_whatever_ends_it() -> None:
    throttle = LoginThrottle(max_failures=1, base_seconds=30, max_seconds=100)
    with pytest.raises(RuntimeError), throttle.attempt("user:alice"):
        raise RuntimeError("the password check failed unexpectedly")
    with throttle.attempt("user:alice"):
        throttle.reset("user:alice")
    with throttle.attempt("user:alice"):
        pass
