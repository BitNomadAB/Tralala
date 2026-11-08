import { useQueries, useQuery } from "@tanstack/react-query";
import { isTalking } from "@/features/discussions/discussionRules";
import { ticketDiscussionsInOrder } from "@/features/discussions/inboxRules";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Discussion } from "@/lib/types";

/** How often the tab looks again while the agents answer in one of the Ticket's discussions. */
const WHILE_TALKING_MS = 15_000;

function talkingIn(data: Discussion | Discussion[] | undefined): number | false {
  const threads = data === undefined ? [] : Array.isArray(data) ? data : [data];
  return threads.some(isTalking) ? WHILE_TALKING_MS : false;
}

/**
 * The Ticket's discussions: the list (`listTicketDiscussions`), read as the Ticket opens so the
 * Discussions tab's count is right at once, and, while the tab shows (`detailed`), each thread
 * under its own key (`keys.discussion`, the key the discussion view reads), because the list
 * carries no verdict and no sides. `rows` are the threads in the tab's order, each the detail
 * once it is read; `ready` once every detail has answered (or failed, when the row keeps the
 * list's fields). While the agents answer in one of them it looks again every 15 s.
 */
export function useTicketDiscussions(boardId: string, cardId: string, detailed: boolean) {
  const list = useQuery({
    queryKey: keys.ticketDiscussions(boardId, cardId),
    queryFn: () => api.listTicketDiscussions(boardId, cardId),
    refetchInterval: (query) => talkingIn(query.state.data),
  });
  const threads = list.data ?? [];
  const details = useQueries({
    queries: threads.map((thread) => ({
      queryKey: keys.discussion(boardId, thread.id),
      queryFn: () => api.getDiscussion(boardId, thread.id),
      enabled: detailed,
      refetchInterval: (query: { state: { data: Discussion | undefined } }) =>
        talkingIn(query.state.data),
    })),
  });
  const rows = ticketDiscussionsInOrder(
    threads.map((thread, index) => details[index]?.data ?? thread),
  );
  return {
    count: list.data?.length,
    loading: list.isLoading || (detailed && details.some((detail) => detail.isPending)),
    error: list.error,
    rows,
  };
}

export type TicketDiscussions = ReturnType<typeof useTicketDiscussions>;
