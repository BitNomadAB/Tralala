import { Avatar } from "@/components/ui/avatar";
import { Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import type { CardNote } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { PendingButton } from "./PendingButton";
import { SAVING } from "./ticketWork";

const LINK =
  "rounded text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** Why a note being edited cannot be saved yet. */
export const NOTE_TEXT_FIRST = "Write the note first.";

/**
 * One note: the author's mark, the text (or its field while edited, which takes the focus) and the
 * author line with Edit for the author. The row carries the note's id and its Edit button a focus
 * mark, so the list can give the focus back to it after a save or a cancel.
 */
export function NoteRow({
  note,
  own,
  editing,
  pending,
  onEdit,
  onChange,
  onSave,
  onDelete,
  onCancel,
}: {
  note: CardNote;
  own: boolean;
  /** The text being edited, or null while the note is read. */
  editing: string | null;
  pending: boolean;
  onEdit: () => void;
  onChange: (text: string) => void;
  onSave: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  return (
    <li
      data-note-id={note.id}
      className="grid grid-cols-[26px_minmax(0,1fr)] items-start gap-2.5 text-[14.5px]"
    >
      <Avatar name={note.author} size="xs" />
      {editing === null ? (
        <div>
          <p className="m-0 mb-0.5 whitespace-pre-wrap">{note.text}</p>
          <div className="mt-[3px] text-[12.5px] text-[var(--foreground-faint)]">
            {note.author} · {formatDate(note.written_at)}
            {own ? (
              <>
                {" · "}
                <button
                  type="button"
                  className={LINK}
                  data-focus-target="edit-note"
                  onClick={onEdit}
                >
                  Edit
                </button>
              </>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="grid gap-2">
          <Textarea
            aria-label="Edit the note"
            autoFocus
            className="min-h-14"
            value={editing}
            onChange={(event) => onChange(event.target.value)}
          />
          <div className="flex flex-wrap items-start gap-2">
            <ReasonButton
              size="sm"
              disabledReason={!editing.trim() ? NOTE_TEXT_FIRST : pending ? SAVING : null}
              onClick={onSave}
            >
              Save
            </ReasonButton>
            <PendingButton variant="outline" size="sm" pending={pending} onClick={onDelete}>
              Delete
            </PendingButton>
            <PendingButton variant="quiet" size="sm" pending={pending} onClick={onCancel}>
              Cancel
            </PendingButton>
          </div>
        </div>
      )}
    </li>
  );
}
