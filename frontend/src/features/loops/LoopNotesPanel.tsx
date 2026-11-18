import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { Field, Textarea } from "@/components/ui/input";
import { Section } from "@/components/ui/section";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { renderMarkdown } from "@/lib/markdown";
import { keys, useLoopNotes } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { BusyButton } from "./BusyButton";

/**
 * The Notes tab: the Loop's log of notes, oldest first, and a box for a person to add one. A note
 * added is announced and the focus is back in the emptied box, ready for the next one.
 */
export function LoopNotesPanel({
  boardId,
  loop,
  readOnly,
}: {
  boardId: string;
  loop: Loop;
  readOnly: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const announce = useAnnounce();
  const notes = useLoopNotes(boardId, loop.id);
  const [draft, setDraft] = useState("");
  const boxId = useId();
  const box = useRef<HTMLTextAreaElement>(null);

  const add = useMutation({
    mutationFn: () => api.addNote(boardId, loop.id, draft.trim()),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: keys.notes(boardId, loop.id) });
      announce("Note added");
      // The button turns unavailable with the box empty, so the focus goes back into the box.
      box.current?.focus();
    },
    onError: (error) => {
      toast.push({
        title: "Could not add the note",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const list = notes.data?.notes ?? [];
  return (
    <Section
      title="Notes"
      count={notes.data ? list.length : undefined}
      level={2}
      className="max-w-3xl"
    >
      <p className="mb-3 text-sm text-[var(--muted-foreground)]">
        What belongs to the Loop and to no single Ticket: the baseline, the checks, a merge, a
        deploy, what is still open.
      </p>
      {list.length === 0 && !notes.isLoading ? (
        <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
          No notes yet.
        </p>
      ) : null}
      <ol aria-label="Notes" className="flex flex-col gap-2">
        {list.map((note) => (
          <li
            key={note.id}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2.5"
          >
            <p className="text-xs text-[var(--muted-foreground)]">
              {note.author_name}
              {note.author_actor_type === "agent" ? " (agent)" : ""} ·{" "}
              <time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time>
            </p>
            <div className="mt-1 text-sm">{renderMarkdown(note.content, { headingLevel: 3 })}</div>
          </li>
        ))}
      </ol>
      {readOnly ? null : (
        <form
          className="mt-3 flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.trim()) add.mutate();
          }}
        >
          <Field label="New note" htmlFor={boxId}>
            <Textarea
              id={boxId}
              ref={box}
              value={draft}
              maxLength={20000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Markdown"
            />
          </Field>
          <div className="flex justify-end">
            <BusyButton type="submit" size="sm" busy={add.isPending} disabled={!draft.trim()}>
              Add note
            </BusyButton>
          </div>
        </form>
      )}
    </Section>
  );
}
