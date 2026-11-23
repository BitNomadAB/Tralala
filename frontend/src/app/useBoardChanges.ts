import { useQuery, useQueryClient, type Query } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";

/** How often an open page asks whether its board changed. */
export const BOARD_CHANGES_INTERVAL_MS = 5_000;

/**
 * What a change of the board refreshes by itself, by the first part of the query key: the listings
 * a person reads (the board and its Loops, a Loop's columns, cards, readiness and notes, a search,
 * the activity, the discussion lists). Never what a draft or a decision is checked against: a
 * Ticket's own view carries the version its changes send, and the planning documents the revisions
 * an approval binds to. Those are read again when the person acts or presses Refresh, so a text
 * under review is never replaced under its reader.
 */
export const FOLLOWED_QUERIES: readonly string[] = [
  "board",
  "loops",
  "loop",
  "lists",
  "cards",
  "readiness",
  "search",
  "activity",
  "notes",
  "discussions",
];

/**
 * Matches the followed queries of one board: each key in `lib/queries.ts` that belongs to a board
 * carries the board's id second.
 */
export function followedQueries(boardId: string): (query: Query) => boolean {
  return (query) =>
    query.queryKey[1] === boardId && FOLLOWED_QUERIES.includes(String(query.queryKey[0]));
}

/** A dialog is open: what it shows is what the person is deciding on. */
function dialogOpen(): boolean {
  return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
}

/**
 * Follows one board for what was changed elsewhere: by an agent over MCP, by another person, in
 * another tab. It asks for the board's change marker every five seconds while the tab is visible,
 * and at once when the tab is shown again; a marker that differs from the last one invalidates the
 * followed queries, which refetch the authoritative state. The first marker is only where the page
 * starts from. A change waits while a dialog is open or a change of the person's own is on its
 * way, and is taken up by a later answer. Nothing is followed while `boardId` is undefined.
 */
export function useBoardChanges(boardId: string | undefined): void {
  const queryClient = useQueryClient();
  const id = boardId ?? "";
  const { data: marker, dataUpdatedAt } = useQuery({
    queryKey: keys.boardChanges(id),
    queryFn: () => api.boardChangeMarker(id),
    enabled: id !== "",
    refetchInterval: BOARD_CHANGES_INTERVAL_MS,
    refetchOnWindowFocus: "always",
    staleTime: 0,
    // A marker is never read from the cache: a board that is opened again starts from a new one.
    gcTime: 0,
    // An answer that fails is asked for again five seconds later anyway.
    retry: false,
  });
  const seen = useRef<{ boardId: string; marker: string } | null>(null);

  // `dataUpdatedAt` is a dependency so that a change which had to wait is looked at again when the
  // next answer arrives, although its marker is the same as in the answer before.
  useEffect(() => {
    if (id === "") {
      seen.current = null;
      return;
    }
    if (marker === undefined) return;
    const last = seen.current;
    if (last?.boardId !== id) {
      seen.current = { boardId: id, marker };
      return;
    }
    if (last.marker === marker) return;
    // The view already shows a change that is on its way, and a refetch now could put the old
    // state back for a moment; a dialog's decision is checked against what it was opened on.
    if (queryClient.isMutating() > 0 || dialogOpen()) return;
    seen.current = { boardId: id, marker };
    void queryClient.invalidateQueries({ predicate: followedQueries(id) });
  }, [id, marker, dataUpdatedAt, queryClient]);
}
