import { useId, useRef } from "react";
import { Expander } from "@/components/ui/expander";
import { HeldButton } from "@/components/ui/held-button";
import { Textarea } from "@/components/ui/input";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { afterDeletedRow, rowOf } from "./afterDelete";
import { NoteRow } from "./NoteRow";
import { notesHint } from "./ticketText";
import { focusTarget, useFocusAfter } from "./useFocusAfter";
import { useTicketNotes } from "./useTicketNotes";

/**
 * "Your notes": what people wrote on the Ticket, each with its author and date, and Edit for the
 * person who wrote it; a composer under the list. Open from the start when there is a note or the
 * Ticket has no face. A read-only Ticket shows its notes and says why there is no composer.
 * Saving and deleting are announced, and the focus goes on (WCAG 2.4.3): back to the note's Edit
 * after a save or a cancel, to the next note after a delete, to the composer after a new note.
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
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const root = useRef<HTMLDivElement>(null);
  const editOf = (noteId: string) =>
    focusTarget(rowOf(root.current, "note-id", noteId), "edit-note");
  // After a delete: the next note's Edit, else the one before, else the section's own button.
  const afterDeleted = (noteId: string) =>
    afterDeletedRow(root.current, { attribute: "note-id", id: noteId, target: "edit-note" }, () =>
      root.current?.closest("details")?.querySelector<HTMLElement>("summary"),
    );

  async function add() {
    if (!(await notes.add())) return;
    announce("Note saved");
    document.getElementById(composer)?.focus();
  }
  return (
    <Expander
      title="Your notes"
      hint={notes.loaded ? notesHint(notes.notes.length) : undefined}
      defaultOpen={openByDefault || notes.notes.length > 0}
    >
      <div ref={root} className="grid gap-2.5">
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
                onSave={() => {
                  void notes.saveEdit(note).then((saved) => {
                    if (!saved) return;
                    announce("Note saved");
                    focusAfter(() => editOf(note.id));
                  });
                }}
                onDelete={() => {
                  void notes.remove(note.id).then((deleted) => {
                    if (!deleted) return;
                    announce("Note deleted");
                    focusAfter(() => afterDeleted(note.id));
                  });
                }}
                onCancel={() => {
                  notes.cancelEdit();
                  focusAfter(() => editOf(note.id));
                }}
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
              void add();
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
              <HeldButton
                type="submit"
                variant="outline"
                size="sm"
                held={notes.pending}
                disabled={!notes.text.trim()}
              >
                Save note
              </HeldButton>
            </div>
          </form>
        )}
      </div>
    </Expander>
  );
}
