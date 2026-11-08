import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { CardNote } from "@/lib/types";

/** What a refused note write reads as. */
export function noteErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "note_author_only") return "Only the person who wrote a note can change it.";
    if (error.code === "version_conflict") return "Someone changed this note. Reload to see it.";
    if (error.code === "loop_read_only") return "This Loop is completed; notes are read-only.";
  }
  return describeError(error, "The note was not saved.");
}

/**
 * A person's notes on a Ticket: the list from its query, the composer's text, the one note being
 * edited, and add, edit (with the version it read) and delete. Every success refetches the list and
 * calls `onChanged`, so the view refetches what records it; a card event refetches the list too.
 */
export function useTicketNotes({
  boardId,
  loopId,
  cardId,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const queryKey = keys.cardNotes(boardId, loopId, cardId);
  const list = useQuery({
    queryKey,
    queryFn: () => api.listCardNotes(boardId, loopId, cardId),
  });
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const settled = {
    onMutate: () => {
      setError(null);
    },
    onError: (mutationError: unknown) => {
      setError(noteErrorText(mutationError));
      void queryClient.invalidateQueries({ queryKey });
    },
  };
  const done = () => {
    void queryClient.invalidateQueries({ queryKey });
    onChanged();
  };

  const add = useMutation({
    mutationFn: (value: string) => api.addCardNote(boardId, loopId, cardId, value),
    ...settled,
    onSuccess: (note: CardNote) => {
      queryClient.setQueryData<CardNote[]>(queryKey, (current) => [...(current ?? []), note]);
      setText("");
      done();
    },
  });

  const edit = useMutation({
    mutationFn: (note: { id: string; text: string; version: number }) =>
      api.editCardNote(boardId, loopId, cardId, note.id, {
        text: note.text,
        version: note.version,
      }),
    ...settled,
    onSuccess: (note: CardNote) => {
      queryClient.setQueryData<CardNote[]>(queryKey, (current) =>
        (current ?? []).map((row) => (row.id === note.id ? note : row)),
      );
      setEditing(null);
      done();
    },
  });

  const remove = useMutation({
    mutationFn: (noteId: string) => api.deleteCardNote(boardId, loopId, cardId, noteId),
    ...settled,
    onSuccess: (_answer: unknown, noteId: string) => {
      queryClient.setQueryData<CardNote[]>(queryKey, (current) =>
        (current ?? []).filter((row) => row.id !== noteId),
      );
      setEditing(null);
      done();
    },
  });

  return {
    notes: list.data ?? [],
    loaded: list.isSuccess,
    text,
    setText,
    editing,
    error,
    pending: add.isPending || edit.isPending || remove.isPending,
    add: () => {
      if (text.trim()) add.mutate(text.trim());
    },
    startEdit: (note: CardNote) => {
      setError(null);
      setEditing({ id: note.id, text: note.text });
    },
    changeEdit: (value: string) => {
      setEditing((current) => (current ? { ...current, text: value } : current));
    },
    cancelEdit: () => {
      setEditing(null);
    },
    saveEdit: (note: CardNote) => {
      if (editing?.id === note.id && editing.text.trim()) {
        edit.mutate({ id: note.id, text: editing.text.trim(), version: note.version });
      }
    },
    remove: (noteId: string) => {
      remove.mutate(noteId);
    },
  };
}
