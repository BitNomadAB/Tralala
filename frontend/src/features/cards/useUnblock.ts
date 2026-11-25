import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Card } from "@/lib/types";
import { NEED_DONE, type TicketNeed } from "./unblock";

/** What the toast says when the other Ticket changed after its row was read; it is read again. */
export const CHANGED_ELSEWHERE = "Someone changed that Ticket. It was read again; try once more.";

/** The request behind each need, sent with the version of the Ticket as it was read. */
function send(boardId: string, loopId: string, card: Card, need: TicketNeed): Promise<Card> {
  switch (need) {
    case "restore":
      return api.restoreCard(boardId, loopId, card.id);
    case "clear_wait":
      return api.clearWait(boardId, loopId, card.id, { version: card.version });
    case "confirm":
      return api.confirmHumanTicket(boardId, loopId, card.id, { version: card.version, note: "" });
    case "complete":
      return api.updateCard(boardId, loopId, card.id, { version: card.version, completed: true });
  }
}

/**
 * What a person does to a Ticket from another Ticket's view, to take away what holds that one up:
 * restore it, clear its wait, confirm it or mark it complete. These are the Ticket's own routes,
 * so the server holds every rule it holds there (the plan's order, the version, a person's
 * decision). Whatever the answer, the Loop's Tickets, each open Ticket view, the plan's readiness,
 * the columns and the Loop are read again, since one Ticket's completion changes what the others
 * wait for. A step that went through is announced; a refusal is a toast.
 */
export function useUnblock({
  boardId,
  loopId,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const announce = useAnnounce();

  const readAgain = () => {
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopCardViews(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.lists(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopSummaries(boardId) });
    onChanged();
  };

  const mutation = useMutation({
    mutationFn: ({ card, need }: { card: Card; need: TicketNeed }) =>
      send(boardId, loopId, card, need),
    onSuccess: (_updated, { need }) => {
      announce(NEED_DONE[need]);
      readAgain();
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.code === "version_conflict") {
        toast.push({ title: CHANGED_ELSEWHERE, variant: "error" });
      } else {
        toast.push({
          title: "Change rejected",
          description: describeError(error, undefined),
          variant: "error",
        });
      }
      readAgain();
    },
  });

  return {
    /** A step is on its way; the next one waits for its answer. */
    pending: mutation.isPending,
    /** Takes one step for `card`; resolves true once the server took it. */
    run: async (card: Card, need: TicketNeed): Promise<boolean> => {
      try {
        await mutation.mutateAsync({ card, need });
        return true;
      } catch {
        return false;
      }
    },
  };
}
