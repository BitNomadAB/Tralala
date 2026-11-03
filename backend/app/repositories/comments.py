"""A Ticket's comments, as ``CommentService`` uses them."""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import CommentsRow


class CommentRepository(Protocol):
    def get(self, comment_id: str) -> CommentsRow | None: ...

    def for_card(self, card_id: str) -> list[CommentsRow]:
        """The card's comments, oldest first, in the order they were written within a second."""
        ...

    def add(self, row: CommentsRow) -> None: ...

    def edit(self, comment_id: str, content: str, *, now: str) -> None:
        """The new content, edited at ``now``."""
        ...

    def delete(self, comment_id: str) -> None:
        """Delete the comment; the mention jobs it started go with it."""
        ...
