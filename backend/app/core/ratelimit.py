from __future__ import annotations

import time
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock

from .errors import RateLimited


class RateLimiter:
    """In-memory sliding-window limiter keyed by actor. Sufficient for a single-host deployment."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self.window = 60.0
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(
                    "Rate limit exceeded",
                    details={"limit": self.limit, "window_seconds": int(self.window)},
                )
            hits.append(now)
            if len(self._hits) > 10_000:
                self._prune(now)

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            self._hits.pop(key, None)


class LoginThrottle:
    """Failure-based exponential backoff per username and per client address.

    Deliberately in-process: the deployment runs one backend per data directory, so no shared
    store is introduced for this.

    Sign-in requests run in parallel (the routes are plain functions in FastAPI's thread pool), so a
    failure recorded after the password check comes too late to stop a burst: every parallel guess
    would pass :meth:`check` before the first one fails. :meth:`attempt` therefore counts an attempt
    from the moment it starts. A key admits as many attempts at once as it has failures left before
    the lock, and one at a time once it has reached the limit, so parallel requests test no more
    passwords than the same requests one after another.
    """

    def __init__(
        self, *, max_failures: int = 5, base_seconds: float = 30.0, max_seconds: float = 900.0
    ) -> None:
        self.max_failures = max_failures
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self._state: dict[str, dict[str, float]] = {}
        self._running: dict[str, int] = {}
        self._lock = Lock()

    def check(self, *keys: str) -> None:
        """Refuse while any of ``keys`` is locked."""
        now = time.monotonic()
        with self._lock:
            self._refuse_locked(keys, now)

    @contextmanager
    def attempt(self, *keys: str) -> Generator[None]:
        """One sign-in attempt against ``keys``; a failure is recorded inside the block."""
        now = time.monotonic()
        with self._lock:
            self._refuse_locked(keys, now)
            for key in keys:
                entry = self._state.get(key)
                left = self.max_failures - (int(entry["failures"]) if entry else 0)
                running = self._running.get(key, 0)
                if running and running >= left:
                    raise RateLimited(
                        "Too many failed sign-in attempts; try again later",
                        details={"retry_after_seconds": 1},
                    )
            for key in keys:
                self._running[key] = self._running.get(key, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                for key in keys:
                    running = self._running.pop(key) - 1
                    if running:
                        self._running[key] = running

    def _refuse_locked(self, keys: tuple[str, ...], now: float) -> None:
        for key in keys:
            entry = self._state.get(key)
            if entry and entry["locked_until"] > now:
                raise RateLimited(
                    "Too many failed sign-in attempts; try again later",
                    details={
                        "retry_after_seconds": int(entry["locked_until"] - now) + 1,
                    },
                )

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                entry = self._state.setdefault(
                    key, {"failures": 0.0, "locked_until": 0.0, "last": 0.0}
                )
                entry["failures"] += 1
                entry["last"] = now
                if entry["failures"] >= self.max_failures:
                    over = entry["failures"] - self.max_failures
                    delay = min(self.base_seconds * (2**over), self.max_seconds)
                    entry["locked_until"] = now + delay
                if len(self._state) > 10_000:
                    self._prune(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._state.pop(key, None)

    def _prune(self, now: float) -> None:
        horizon = self.max_seconds * 2
        for key in [
            k
            for k, v in self._state.items()
            if v["locked_until"] <= now and now - v["last"] > horizon
        ]:
            self._state.pop(key, None)
