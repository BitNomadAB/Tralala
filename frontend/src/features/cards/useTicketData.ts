import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api } from "@/lib/api";
import {
  keys,
  useActivity,
  useBoard,
  useBoardPeople,
  useLabels,
  useLists,
  useLoop,
  useReadiness,
} from "@/lib/queries";
import { useCardEvents } from "./useCardEvents";

/**
 * What the Ticket view reads: the card with its checklists and comments, the Loop's columns, the
 * board and the Loop (for read-only), the plan's readiness (the Phase's name and the dependencies),
 * the board's labels and people, and the card's history. Over the Kanban these are the queries the
 * Loop page already holds, so the dialog fetches only the card's own. `refresh` refetches whatever
 * a change of the card touches; `live` says the card's events are followed.
 */
export function useTicketData(boardId: string, loopId: string, cardId: string) {
  const queryClient = useQueryClient();
  const card = useQuery({
    queryKey: keys.card(boardId, loopId, cardId),
    queryFn: () => api.getCard(boardId, loopId, cardId),
  });
  const board = useBoard(boardId);
  const loop = useLoop(boardId, loopId);
  const lists = useLists(boardId, loopId);
  const readiness = useReadiness(boardId, loopId);
  const labels = useLabels(boardId);
  const people = useBoardPeople(boardId);
  const activity = useActivity(boardId, cardId);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.card(boardId, loopId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId) });
    void queryClient.invalidateQueries({ queryKey: keys.mentions(boardId, loopId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.cardNotes(boardId, loopId, cardId) });
  }, [queryClient, boardId, loopId, cardId]);

  const live = useCardEvents(boardId, loopId, cardId, refresh);

  const readOnly =
    (board.data !== undefined && board.data.status !== "active") ||
    (loop.data !== undefined &&
      (loop.data.stage === "completed" ||
        loop.data.stage === "cancelled" ||
        loop.data.archived_at !== null));

  return {
    card,
    board: board.data,
    loop: loop.data,
    lists: lists.data ?? [],
    readiness: readiness.data,
    labels: labels.data ?? [],
    people: people.data ?? [],
    history: activity.data ?? [],
    refresh,
    live,
    readOnly,
  };
}
