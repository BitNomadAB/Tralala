import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Card, CardDetail, Wait } from "@/lib/types";

/** What a refused change reads as under the section. */
export function workErrorText(error: unknown): string {
  if (error instanceof ApiError && error.code === "version_conflict") {
    return "Someone else changed this Ticket. Reload to see the latest version.";
  }
  return describeError(error, "The change was not saved.");
}

/**
 * The two changes a person makes to what a Ticket waits for: set a wait, clear it. Each sends the
 * card's current version; the answer is the updated card, written into the card's query at once so
 * the next change carries the new version, before `onChanged` refetches the rest.
 */
export function useCardWork({
  boardId,
  loopId,
  card,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const settled = {
    onMutate: () => {
      setError(null);
    },
    onSuccess: (updated: Card) => {
      queryClient.setQueryData<CardDetail>(keys.card(boardId, loopId, card.id), (current) =>
        current ? { ...current, ...updated } : updated,
      );
      void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
      onChanged();
    },
    onError: (mutationError: unknown) => {
      setError(workErrorText(mutationError));
      onChanged();
    },
  };

  const wait = useMutation({
    mutationFn: (value: { waiting_for: Wait; reason: string }) =>
      api.setWait(boardId, loopId, card.id, { version: card.version, ...value }),
    ...settled,
  });

  const clear = useMutation({
    mutationFn: () => api.clearWait(boardId, loopId, card.id, { version: card.version }),
    ...settled,
  });

  return {
    error,
    pending: wait.isPending || clear.isPending,
    /** Resolves true once the wait is saved, so the form can close. */
    setWait: async (value: { waiting_for: Wait; reason: string }): Promise<boolean> => {
      try {
        await wait.mutateAsync(value);
        return true;
      } catch {
        return false;
      }
    },
    clearWait: () => {
      clear.mutate();
    },
  };
}
