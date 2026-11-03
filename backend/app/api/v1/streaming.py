"""Shared server-sent-event plumbing for discussion and ticket streams.

Subscribing happens before the replay, so an event that commits between the two steps is delivered
once (the replay's sequence numbers are tracked in ``last``). The stream always yields a comment
frame first: without it an idle scope would keep the client in ``CONNECTING`` until the first
heartbeat.

An open stream spends nearly all of its life in a worker thread waiting for the next event. Those
waits take their tokens from :func:`stream_limiter`, not from anyio's default limiter, so open
streams cannot use up the thread pool that the routes run in (``THREADPOOL_TOKENS`` in
``app/main.py``). Beyond ``EVENT_STREAM_TOKENS`` open streams a wait queues for its turn, which
delays events instead of stalling requests.
"""

from __future__ import annotations

import json
import queue
from collections.abc import Callable
from typing import Any

import anyio
from anyio.lowlevel import RunVar
from fastapi import Request

HEARTBEAT_SECONDS = 15.0
EVENT_STREAM_TOKENS = 100

_stream_limiter: RunVar[anyio.CapacityLimiter] = RunVar("tralala_event_stream_limiter")


def stream_limiter() -> anyio.CapacityLimiter:
    """The running event loop's limiter for stream waits, created on first use like anyio's own."""
    try:
        return _stream_limiter.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(EVENT_STREAM_TOKENS)
        _stream_limiter.set(limiter)
        return limiter


def sse_frame(event: dict[str, Any]) -> str:
    return (
        f"id: {event['seq']}\n"
        f"event: {event['type']}\n"
        f"data: {json.dumps(event)}\n\n"
    )


def event_stream(
    request: Request,
    *,
    after: int,
    subscribe: Callable[[], queue.Queue],
    unsubscribe: Callable[[queue.Queue], None],
    replay: Callable[[], list[dict[str, Any]]],
) -> Any:
    listener = subscribe()

    async def stream() -> Any:
        last = after
        try:
            yield ": connected\n\n"
            for event in await anyio.to_thread.run_sync(replay):
                last = int(event["seq"])
                yield sse_frame(event)
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await anyio.to_thread.run_sync(
                        lambda: listener.get(timeout=1.0), limiter=stream_limiter()
                    )
                except queue.Empty:
                    idle += 1.0
                    if idle >= HEARTBEAT_SECONDS:
                        idle = 0.0
                        yield ": keep-alive\n\n"
                    continue
                idle = 0.0
                if int(event["seq"]) <= last:
                    continue
                last = int(event["seq"])
                yield sse_frame(event)
        finally:
            unsubscribe(listener)

    return stream()


STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

__all__ = [
    "EVENT_STREAM_TOKENS",
    "HEARTBEAT_SECONDS",
    "STREAM_HEADERS",
    "event_stream",
    "sse_frame",
    "stream_limiter",
]
