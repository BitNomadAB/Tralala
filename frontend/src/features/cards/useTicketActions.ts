import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { BoardList, Card, CardDetail, Workplace } from "@/lib/types";
import { startWorkTarget } from "./ticketRules";

/** What the toast says when the version the view sent is no longer the Ticket's. */
export const CONFLICT_TEXT = "Someone changed this Ticket. Reload to see it.";

/** A card change as `PATCH` takes it, the version left to the hook. */
export type TicketChange = Omit<Parameters<typeof api.updateCard>[3], "version">;

/** Where a moved card goes in its new column: the end, as the Kanban's drop does. */
const AT_THE_END = 10_000;

/**
 * Every change the Ticket's head and rail make: a field through `PATCH` with the version, a move,
 * Start work (assign the signed-in person when nobody owns it, then move to the next column),
 * completion, a person's confirmation, the workplace and archiving. Each answer is written into
 * the card's query at once, so the next change carries the new version, before `refresh` refetches
 * the rest. A refusal is a toast; a `409 version_conflict` says to reload, and the refetch puts
 * the field back to what the server holds.
 */
export function useTicketActions({
  boardId,
  loopId,
  card,
  lists,
  actorId,
  refresh,
  onArchived,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  lists: readonly BoardList[];
  /** The signed-in person, whom Start work assigns. */
  actorId: string | null;
  refresh: () => void;
  onArchived: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();

  const mutation = useMutation({
    mutationFn: (run: () => Promise<Card>) => run(),
    onSuccess: (updated: Card) => {
      queryClient.setQueryData<CardDetail>(keys.card(boardId, loopId, card.id), (current) =>
        current ? { ...current, ...updated } : updated,
      );
      void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
      void queryClient.invalidateQueries({ queryKey: keys.lists(boardId, loopId) });
      void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
      refresh();
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.code === "version_conflict") {
        toast.push({ title: CONFLICT_TEXT, variant: "error" });
      } else {
        toast.push({
          title: "Change rejected",
          description: describeError(error, undefined),
          variant: "error",
        });
      }
      refresh();
    },
  });

  /** Runs one change; resolves true once the server took it. */
  async function run(change: () => Promise<Card>): Promise<boolean> {
    try {
      await mutation.mutateAsync(change);
      return true;
    } catch {
      return false;
    }
  }

  const archive = useMutation({
    mutationFn: () => api.archiveCard(boardId, loopId, card.id),
    onSuccess: () => {
      refresh();
      onArchived();
      toast.push({ title: "Ticket archived", variant: "success" });
    },
    onError: (error: unknown) => {
      toast.push({
        title: "Change rejected",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const update = (change: TicketChange) =>
    run(() => api.updateCard(boardId, loopId, card.id, { version: card.version, ...change }));

  const move = (listId: string) =>
    run(() =>
      api.moveCard(boardId, loopId, card.id, {
        version: card.version,
        list_id: listId,
        position: AT_THE_END,
      }),
    );

  const target = startWorkTarget(card, lists);

  const startWork = () =>
    run(async () => {
      let current = card;
      if (current.assignee_actor_id === null && actorId !== null) {
        current = await api.updateCard(boardId, loopId, card.id, {
          version: current.version,
          assignee_actor_id: actorId,
        });
      }
      if (!target) return current;
      return api.moveCard(boardId, loopId, card.id, {
        version: current.version,
        list_id: target.id,
        position: AT_THE_END,
      });
    });

  return {
    pending: mutation.isPending || archive.isPending,
    /** The column Start work moves to; null when Start work is not the decision. */
    startTarget: target,
    update,
    move,
    startWork,
    setCompleted: (completed: boolean) => update({ completed }),
    /** A human-only Ticket is completed by a person's confirmation. */
    confirm: (note: string) =>
      run(() => api.confirmHumanTicket(boardId, loopId, card.id, { version: card.version, note })),
    assign: (actorIdOrNobody: string | null) =>
      actorIdOrNobody === null
        ? update({ clear_assignee: true })
        : update({ assignee_actor_id: actorIdOrNobody }),
    setWorkplace: (workplace: Workplace) =>
      run(() => api.setWorkplace(boardId, loopId, card.id, { version: card.version, workplace })),
    archive: () => {
      archive.mutate();
    },
  };
}

export type TicketActions = ReturnType<typeof useTicketActions>;
