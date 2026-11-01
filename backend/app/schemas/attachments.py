from __future__ import annotations

from .common import OutModel


class AttachmentOut(OutModel):
    id: str
    card_id: str | None = None
    discussion_id: str | None = None
    message_id: str | None = None
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by_actor_id: str
    created_at: str
    deleted_at: str | None = None


__all__ = ["AttachmentOut"]
