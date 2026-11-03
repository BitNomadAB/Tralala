"""Stored answers to requests that carried an ``Idempotency-Key``.

A record is keyed by the actor and the key, and holds a fingerprint of the request and the answer
it got, so a retried request is answered from here instead of being carried out twice. The registry
keeps the records of the requests that create a board, which run before a board database exists;
a board keeps the records of the requests that write into it (a Loop, a Ticket).
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated import board
from ..db.generated.registry import IdempotencyRecordsRow


class RegistryIdempotencyRepository(Protocol):
    def get(self, actor_id: str, key: str) -> IdempotencyRecordsRow | None:
        """The record, expired or not: the caller decides what an old one means."""
        ...

    def put(self, row: IdempotencyRecordsRow) -> None:
        """Store the record, replacing the one held for the same actor and key."""
        ...


class BoardIdempotencyRepository(Protocol):
    def get(self, actor_id: str, key: str) -> board.IdempotencyRecordsRow | None:
        """The record, expired or not: the caller decides what an old one means."""
        ...

    def delete(self, actor_id: str, key: str) -> None: ...

    def put(self, row: board.IdempotencyRecordsRow) -> None:
        """Store the record, replacing the one held for the same actor and key."""
        ...
