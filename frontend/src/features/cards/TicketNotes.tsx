import { useId } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Expander } from "@/components/ui/expander";
import { Textarea } from "@/components/ui/input";
import type { CardNote } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { notesHint } from "./ticketText";
import { useTicketNotes } from "./useTicketNotes";

const LINK =
  "rounded text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * "Your notes": what people wrote on the Ticket, each with its author and date, and Edit for the
 * person who wrote it; a composer under the list. Open from the start when there is a note or the
 * Ticket has no face. A read-only Ticket shows its notes and says why there is no composer.
 */
export function TicketNotes({
  boardId,
  loopId,
  cardId,
  actorId,
  readOnly,
  readOnlyText,
  openByDefault,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  /** The signed-in person: only their own notes can be edited. */
  actorId: string | undefined;
  readOnly: boolean;
  /** Why nothing can be written, shown in place of the composer. */
  readOnlyText: string;
  /** Open without a note too (a Ticket without a face). */
  openByDefault: boolean;
  onChanged: () => void;
}) {
  const notes = useTicketNotes({ boardId, loopId, cardId, onChanged });
  const composer = useId();
  const helper = useId();
  return (
    <Expander
      title="Your notes"
      hint={notes.loaded ? notesHint(notes.notes.length) : undefined}
      defaultOpen={openByDefault || notes.notes.length > 0}
    >
      <div className="grid gap-2.5">
        {notes.notes.length > 0 ? (
          <ul aria-label="Your notes" className="m-0 grid list-none gap-2.5 p-0">
            {notes.notes.map((note) => (
              <NoteRow
                key={note.id}
                note={note}
                own={!readOnly && actorId !== undefined && note.author_actor_id === actorId}
                editing={notes.editing?.id === note.id ? notes.editing.text : null}
                pending={notes.pending}
                onEdit={() => notes.startEdit(note)}
                onChange={notes.changeEdit}
                onSave={() => notes.saveEdit(note)}
                onDelete={() => notes.remove(note.id)}
                onCancel={notes.cancelEdit}
              />
            ))}
          </ul>
        ) : null}
        {notes.error ? (
          <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
            {notes.error}
          </p>
        ) : null}
        {readOnly ? (
          <p className="m-0 text-[12.5px] text-[var(--foreground-faint)]">{readOnlyText}</p>
        ) : (
          <form
            className="grid gap-2.5"
            onSubmit={(event) => {
              event.preventDefault();
              notes.add();
            }}
          >
            <Textarea
              id={composer}
              aria-label="Add a note"
              aria-describedby={helper}
              className="min-h-14 bg-[var(--surface)]"
              placeholder="Add a note about this Ticket. Written by you, never by an agent."
              value={notes.text}
              onChange={(event) => notes.setText(event.target.value)}
            />
            <div className="flex flex-wrap items-center justify-between gap-2.5">
              <small id={helper} className="text-[12.5px] text-[var(--foreground-faint)]">
                Your notes stay with the Ticket and your coding agent can read them.
              </small>
              <Button
                type="submit"
                variant="outline"
                size="sm"
                disabled={notes.pending || !notes.text.trim()}
              >
                Save note
              </Button>
            </div>
          </form>
        )}
      </div>
    </Expander>
  );
}

/** One note: the author's mark, the text (or its field while edited) and the author line. */
function NoteRow({
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
    <li className="grid grid-cols-[26px_minmax(0,1fr)] items-start gap-2.5 text-[14.5px]">
      <Avatar name={note.author} size="xs" />
      {editing === null ? (
        <div>
          <p className="m-0 mb-0.5 whitespace-pre-wrap">{note.text}</p>
          <div className="mt-[3px] text-[12.5px] text-[var(--foreground-faint)]">
            {note.author} · {formatDate(note.written_at)}
            {own ? (
              <>
                {" · "}
                <button type="button" className={LINK} onClick={onEdit}>
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
            className="min-h-14"
            value={editing}
            onChange={(event) => onChange(event.target.value)}
          />
          <div className="flex gap-2">
            <Button size="sm" disabled={pending || !editing.trim()} onClick={onSave}>
              Save
            </Button>
            <Button variant="outline" size="sm" disabled={pending} onClick={onDelete}>
              Delete
            </Button>
            <Button variant="quiet" size="sm" disabled={pending} onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
