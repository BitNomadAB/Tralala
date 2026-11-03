import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { renderMarkdown } from "@/lib/markdown";
import { keys, useLoopNotes } from "@/lib/queries";
import type { Loop } from "@/lib/types";

/** The Loop's log of notes, oldest first, and a box for a person to add one. */
export function LoopNotesPanel({
  boardId,
  loop,
  open,
  readOnly,
  onClose,
}: {
  boardId: string;
  loop: Loop;
  open: boolean;
  readOnly: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const notes = useLoopNotes(boardId, loop.id, open);
  const [draft, setDraft] = useState("");

  const add = useMutation({
    mutationFn: () => api.addNote(boardId, loop.id, draft.trim()),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: keys.notes(boardId, loop.id) });
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
    <Dialog open={open} onOpenChange={(value) => (!value ? onClose() : undefined)}>
      <DialogContent
        title={`${loop.key} notes`}
        description="What belongs to the Loop and to no single Ticket: the baseline, the checks, a merge, a deploy, what is still open."
        className="w-[min(760px,96vw)]"
      >
        {list.length === 0 && !notes.isLoading ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
            No notes yet.
          </p>
        ) : null}
        <ol aria-label="Notes" className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto">
          {list.map((note) => (
            <li
              key={note.id}
              className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2.5"
            >
              <p className="text-[11px] text-[var(--muted-foreground)]">
                {note.author_name}
                {note.author_actor_type === "agent" ? " (agent)" : ""} ·{" "}
                <time dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time>
              </p>
              <div className="mt-1 text-sm">{renderMarkdown(note.content)}</div>
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
            <Textarea
              aria-label="New note"
              value={draft}
              maxLength={20000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Markdown"
            />
            <div className="flex justify-end">
              <Button type="submit" size="sm" disabled={!draft.trim() || add.isPending}>
                Add note
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
