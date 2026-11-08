import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { BoardList, Card } from "@/lib/types";
import { LIST_LIMIT } from "./loopUi";
import { ticketHrefResolver } from "./ticketLinks";

/** The Kanban's filters: words, a priority and overdue only. */
export interface TicketFilters {
  q: string;
  priority: "" | Card["priority"];
  overdue: boolean;
}

export const NO_FILTERS: TicketFilters = { q: "", priority: "", overdue: false };

/**
 * The Loop's cards column by column (the query keys the drag and drop writes to), the ids the
 * filters match (null when no filter is set) and the resolver that links a Ticket key in a text to
 * that Ticket when this Loop has it.
 */
export function useLoopCards({
  boardId,
  loopId,
  lists,
  filters,
}: {
  boardId: string;
  loopId: string;
  lists: BoardList[];
  filters: TicketFilters;
}) {
  const cardQueries = useQueries({
    queries: lists.map((list) => ({
      queryKey: keys.listCards(boardId, loopId, list.id, LIST_LIMIT),
      queryFn: () => api.listCards(boardId, loopId, { list_id: list.id, limit: LIST_LIMIT }),
      enabled: Boolean(boardId && loopId),
    })),
  });

  const cardsByList = useMemo(() => {
    const map: Record<string, Card[]> = {};
    lists.forEach((list, index) => {
      map[list.id] = cardQueries[index]?.data ?? [];
    });
    return map;
  }, [lists, cardQueries]);

  // A Ticket key in a description links to that Ticket when this Loop has it; others stay text.
  const ticketHref = useMemo(
    () => ticketHrefResolver(boardId, loopId, Object.values(cardsByList).flat()),
    [boardId, loopId, cardsByList],
  );

  const filtersActive = Boolean(filters.q.trim() || filters.priority || filters.overdue);
  const searchQuery = useQuery({
    queryKey: keys.search(boardId, loopId, { ...filters }),
    queryFn: () =>
      api.searchCards(boardId, loopId, {
        q: filters.q.trim() || undefined,
        priority: filters.priority || undefined,
        overdue: filters.overdue || undefined,
        limit: 200,
      }),
    enabled: Boolean(boardId && loopId) && filtersActive,
  });

  const matchingIds = useMemo(() => {
    if (!filtersActive) return null;
    return new Set((searchQuery.data?.items ?? []).map((card) => card.id));
  }, [filtersActive, searchQuery.data]);

  return { cardsByList, ticketHref, matchingIds };
}
