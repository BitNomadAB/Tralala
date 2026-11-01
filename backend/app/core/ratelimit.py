from __future__ import annotations

import time
from collections import deque
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
    """

    def __init__(
        self, *, max_failures: int = 5, base_seconds: float = 30.0, max_seconds: float = 900.0
    ) -> None:
        self.max_failures = max_failures
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self._state: dict[str, dict[str, float]] = {}
        self._lock = Lock()

    def check(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
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
