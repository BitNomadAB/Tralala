"""The metadata of a board's uploaded files, as ``AttachmentService`` uses it.

The bytes live in the board's attachments directory (``BoardFiles.attachments_dir``); a row names
its file by ``stored_filename``. A deleted attachment keeps its row with ``deleted_at`` set.
"""

from __future__ import annotations

from typing import Protocol

from ..db.generated.board import AttachmentsRow


class AttachmentRepository(Protocol):
    def live(self, *, card_id: str | None) -> list[AttachmentsRow]:
        """The attachments that are not deleted, oldest first; only the card's when ``card_id`` is
        set."""
        ...

    def get_live(self, attachment_id: str) -> AttachmentsRow | None:
        """The attachment, unless it is deleted."""
        ...

    def live_size(self) -> int:
        """The bytes of every attachment of the board that is not deleted."""
        ...

    def add(self, row: AttachmentsRow) -> None: ...

    def mark_deleted(self, attachment_id: str, *, now: str) -> None: ...
