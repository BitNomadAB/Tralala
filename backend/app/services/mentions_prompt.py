"""What a mentioned agent is told: its Ticket, the recent thread, text attachments and the comment.

``MentionService`` opens the board reader and calls ``mention_messages`` with the registry (to name
who wrote each earlier comment) and the attachment files (to excerpt text attachments).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict

from ..db.generated.board import AttachmentsRow, CommentMentionJobsRow, CommentsRow
from ..repositories.board import BoardRepositories
from ..repositories.board_files import AttachmentFiles
from ..repositories.registry import RegistryUnitOfWork

RECENT_COMMENTS = 20
CONTEXT_CHARS = 4000
# A mentioned agent should be able to read the notes that were uploaded with the ticket, but not
# swallow a whole file: only text-like attachments, and only a bounded head of each.
TEXT_ATTACHMENT_TYPES = {"application/json", "application/xml", "application/x-yaml"}
ATTACHMENT_EXCERPTS = 3
ATTACHMENT_EXCERPT_BYTES = 200_000
ATTACHMENT_EXCERPT_CHARS = 2_000


class Speaker(TypedDict):
    name: str
    type: str


def attachment_excerpt(directory: Path, attachment: AttachmentsRow) -> str:
    """Head of a text attachment, for the agent that was mentioned on its ticket.

    Binary formats stay metadata only: extracting them would need a parser per format, and a
    mention should never attach megabytes to a prompt.
    """
    content_type = attachment.content_type or ""
    if not (content_type.startswith("text/") or content_type in TEXT_ATTACHMENT_TYPES):
        return ""
    if attachment.size_bytes > ATTACHMENT_EXCERPT_BYTES:
        return ""
    if not attachment.stored_filename:
        return ""
    try:
        raw = (directory / attachment.stored_filename).read_bytes()
    except OSError:
        return ""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    if len(text) <= ATTACHMENT_EXCERPT_CHARS:
        return text
    return text[:ATTACHMENT_EXCERPT_CHARS] + "\n(truncated)"


def mention_messages(
    repos: BoardRepositories,
    job: CommentMentionJobsRow,
    board_id: str,
    *,
    registry: RegistryUnitOfWork,
    files: AttachmentFiles,
) -> list[dict[str, str]] | None:
    """The prompt for ``job``'s agent, or None when its Ticket or comment is gone."""
    card = repos.cards.get(job.card_id)
    comment = repos.comments.get(job.comment_id)
    if card is None or comment is None:
        return None
    listed = repos.lists.get(card.list_id) if card.list_id else None
    loop = repos.loops.get(card.loop_id)
    labels = [label.name for label in repos.cards.labels([job.card_id]).get(job.card_id, [])]
    checklists = repos.checklists.for_card(job.card_id)
    items = repos.checklist_items.for_card(job.card_id)
    earlier = [
        entry for entry in repos.comments.for_card(job.card_id) if entry.id != job.comment_id
    ]
    history = earlier[-RECENT_COMMENTS:]
    attachments = repos.attachments.live(card_id=job.card_id)
    speakers = mention_speakers(registry, history)

    lines = [
        f"Loop: {(loop.name if loop else None) or '(unknown)'}"
        f" ({(loop.key if loop else None) or 'no key'})",
        f"Ticket: {card.title}",
        f"Ticket id: {job.card_id} (key: {card.ticket_key or 'not keyed yet'})",
        f"List: {(listed.name if listed else None) or '(unknown)'}",
        f"Priority: {card.priority}",
        f"Due: {card.due_at or 'none'}",
        f"Status: {'completed' if card.completed_at else 'open'}",
        f"Labels: {', '.join(labels) if labels else 'none'}",
        f"Description:\n{(card.description or '(empty)')[:CONTEXT_CHARS]}",
    ]
    if checklists:
        lines.append("Checklists:")
        for checklist in checklists:
            entries = [item for item in items if item.checklist_id == checklist.id]
            rendered = "; ".join(
                f"[{'x' if item.completed else ' '}] {item.text}" for item in entries
            )
            lines.append(f"- {checklist.title}: {rendered or '(no items)'}")
    if attachments:
        lines.append("Attachments:")
        excerpts = 0
        for attachment in attachments[:20]:
            lines.append(
                f"- {attachment.original_filename} ({attachment.content_type},"
                f" {attachment.size_bytes} bytes)"
            )
            if excerpts < ATTACHMENT_EXCERPTS:
                excerpt = attachment_excerpt(files.attachments_dir(board_id), attachment)
                if excerpt:
                    excerpts += 1
                    lines.append("  content:\n" + excerpt)
    transcript = "\n".join(spoken(entry, speakers) for entry in history)
    sections = ["\n".join(lines)]
    if transcript:
        sections.append(f"Recent comments:\n{transcript}")
    sections.append(f"Comment that mentioned you:\n{comment.content[:CONTEXT_CHARS]}")
    sections.append(
        "You were mentioned in this ticket. Answer the comment in the ticket thread as your "
        "role: be concise, concrete and actionable. Do not repeat the ticket back. Never "
        "mention other agents."
    )
    return [{"role": "user", "content": "\n\n".join(sections)}]


def mention_speakers(
    registry: RegistryUnitOfWork, comments: Sequence[CommentsRow]
) -> dict[str, Speaker]:
    """Who wrote each comment: a person or token by its actor, an agent by its name."""
    missing = {comment.actor_id for comment in comments if comment.actor_id}
    if not missing:
        return {}
    with registry.reader() as accounts:
        actors = accounts.actors.many(missing)
        agents = accounts.agents.names(missing)
    known: dict[str, Speaker] = {
        actor_id: {"name": row.name, "type": row.type} for actor_id, row in actors.items()
    }
    known.update(
        {agent_id: {"name": name, "type": "agent"} for agent_id, name in agents.items()}
    )
    return known


def spoken(comment: CommentsRow, speakers: Mapping[str, Speaker]) -> str:
    speaker = speakers.get(comment.actor_id)
    name = speaker["name"] if speaker else None
    kind = speaker["type"] if speaker else None
    return f"[{name or 'Unknown'} · {kind or 'user'}] {comment.content[:1000]}"
