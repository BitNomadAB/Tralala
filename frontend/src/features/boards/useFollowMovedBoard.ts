import { useEffect, useRef } from "react";
import { focusById } from "@/features/settings/removalFocus";
import type { Board } from "@/lib/types";

/** A board that archiving or restoring moves to the other list of the dashboard. */
export interface MovedBoard {
  boardId: string;
  archived: boolean;
}

/** The "more" button of the tile of `boardId`, where the person chose Archive or Restore. */
function tileMenuButton(boardId: string): HTMLElement | null {
  const tile = Array.from(document.querySelectorAll<HTMLElement>("li[data-board-id]")).find(
    (element) => element.dataset.boardId === boardId,
  );
  return tile?.querySelector<HTMLElement>('[aria-haspopup="menu"]') ?? null;
}

/**
 * Keeps focus with a board that archiving or restoring moved from one list to the other (WCAG
 * 2.4.3): its tile is drawn anew in the other list, so focus would otherwise fall to the start of
 * the page. Once `boards` shows the board in its new state, focus goes to the "more" button of its
 * new tile; when the board is no longer listed (a filter hides it), to `fallbackId`. The board
 * waits in a ref: the list's refetch, not the call, is what renders again.
 */
export function useFollowMovedBoard(
  boards: readonly Board[] | undefined,
  fetching: boolean,
  fallbackId: string,
): (moved: MovedBoard) => void {
  const moved = useRef<MovedBoard | null>(null);
  useEffect(() => {
    const waiting = moved.current;
    if (waiting === null || boards === undefined) return;
    const board = boards.find((entry) => entry.id === waiting.boardId);
    const arrived = board !== undefined && (board.status === "archived") === waiting.archived;
    // Not there yet: the list still shows the board as it was, or is still being fetched.
    if (!arrived && (fetching || board !== undefined)) return;
    moved.current = null;
    const target = arrived ? tileMenuButton(waiting.boardId) : null;
    if (target) target.focus();
    else focusById(fallbackId);
  }, [boards, fetching, fallbackId]);
  return (next: MovedBoard) => {
    moved.current = next;
  };
}
