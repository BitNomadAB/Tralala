"""A Loop's notes, as ``LoopNoteService`` and the history snapshot use them."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import LoopNotesRow


class LoopNoteRepository(Protocol):
    def add(self, row: LoopNotesRow) -> None: ...

    def page(self, loop_id: str, *, limit: int, before: str | None) -> list[LoopNotesRow]:
        """The newest ``limit`` notes written before the note ``before`` (every note when it is
        None), oldest first; notes of one second keep the order they were written in."""
        ...

    def for_loop(self, loop_id: str) -> list[LoopNotesRow]:
        """Every note of the Loop, oldest first."""
        ...

    def count(self, loop_id: str) -> int: ...

    def latest_by(self, loop_id: str, actor_id: str, content_sha256: str) -> LoopNotesRow | None:
        """The actor's newest note of the Loop with this content, if any."""
        ...
