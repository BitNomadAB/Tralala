import { useRef, useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { HeldButton } from "@/components/ui/held-button";
import { Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import type { CardNote } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { noteExcerpt } from "./ticketText";
import { SAVING } from "./ticketWork";
import { focusTarget, useFocusAfter } from "./useFocusAfter";

const LINK =
  "rounded text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/** Why a note being edited cannot be saved yet. */
export const NOTE_TEXT_FIRST = "Write the note first.";

/**
 * One note: the author's mark, the text (or its field while edited, which takes the focus) and the
 * author line with Edit for the author. The row carries the note's id and its Edit button a focus
 * mark, so the list can give the focus back to it after a save or a cancel. Delete asks once, as a
 * file's delete does: "Delete this note?" with the focus on Keep, which gives it back to Delete.
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
  const [confirming, setConfirming] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  const focusAfter = useFocusAfter();
  return (
    <li
      ref={row}
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
                  aria-label={`Edit note “${noteExcerpt(note.text)}”`}
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
          {confirming ? (
            // Keyed apart from the buttons, so Keep mounts anew and takes the focus.
            <div key="confirm" className="flex flex-wrap items-center gap-2 text-[13px]">
              <span>Delete this note?</span>
              <HeldButton variant="danger" size="sm" held={pending} onClick={onDelete}>
                {pending ? "Deleting…" : "Delete"}
              </HeldButton>
              <HeldButton
                variant="outline"
                size="sm"
                autoFocus
                held={pending}
                onClick={() => {
                  setConfirming(false);
                  focusAfter(() => focusTarget(row.current, "delete-note"));
                }}
              >
                Keep
              </HeldButton>
            </div>
          ) : (
            <div key="buttons" className="flex flex-wrap items-start gap-2">
              <ReasonButton
                size="sm"
                disabledReason={!editing.trim() ? NOTE_TEXT_FIRST : pending ? SAVING : null}
                onClick={onSave}
              >
                Save
              </ReasonButton>
              <HeldButton
                variant="outline"
                size="sm"
                data-focus-target="delete-note"
                held={pending}
                onClick={() => setConfirming(true)}
              >
                Delete
              </HeldButton>
              <HeldButton variant="quiet" size="sm" held={pending} onClick={onCancel}>
                Cancel
              </HeldButton>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
