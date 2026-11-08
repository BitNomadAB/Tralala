import { useQueries } from "@tanstack/react-query";
import { isFinished, loopNextAction, type LoopNextAction } from "@/features/loops/loopNextAction";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { Board, LoopSummary } from "@/lib/types";

/** One board's Loop summaries as the dashboard holds them while they load. */
export interface BoardSummaries {
  loops: LoopSummary[] | undefined;
  pending: boolean;
  failed: boolean;
}

/** One row of "Waits for you": a Loop whose next step is a person's decision. */
export interface WaitingRow {
  board: Board;
  loop: LoopSummary;
  action: LoopNextAction;
}

/**
 * Whether a board's Loops can be summarised: an active board, or an archived one (read-only, but
 * its Loops still stand somewhere). A board in maintenance or after a failed migration cannot be
 * opened, so it is not asked.
 */
export function summarisable(board: Board): boolean {
  return board.status === "active" || board.status === "archived";
}

/**
 * The Loop summaries of every board given, one request a board and all of them in parallel; a
 * board listed twice (a tile and the waiting list) is asked once. The map fills in as each answer
 * arrives, so a tile renders before the slowest board has answered.
 */
export function useBoardSummaries(boards: readonly Board[]): Map<string, BoardSummaries> {
  const ids = [...new Set(boards.filter(summarisable).map((board) => board.id))];
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.loopSummaries(id),
      queryFn: () => api.listLoopSummaries(id),
    })),
  });
  const byBoard = new Map<string, BoardSummaries>();
  ids.forEach((id, index) => {
    const result = results[index];
    if (!result) return;
    byBoard.set(id, {
      loops: result.data?.loops,
      pending: result.isPending,
      failed: result.isError,
    });
  });
  return byBoard;
}

/**
 * The Loops that wait for a person's decision, across the boards given, in the boards' order and
 * each board's Loops in the server's order. Only an active board decides anything: an archived one
 * is read-only.
 */
export function waitingRows(
  boards: readonly Board[],
  summaries: ReadonlyMap<string, BoardSummaries>,
): WaitingRow[] {
  const rows: WaitingRow[] = [];
  for (const board of boards) {
    if (board.status !== "active") continue;
    for (const loop of summaries.get(board.id)?.loops ?? []) {
      const action = loopNextAction(loop);
      if (action.decision) rows.push({ board, loop, action });
    }
  }
  return rows;
}

/**
 * A tile's small words: how many Loops are in progress (open, neither completed nor cancelled) and
 * how many of them wait for a decision; a read-only board waits for none, since nothing can be
 * decided there.
 */
export function tileCounts(
  loops: readonly LoopSummary[],
  readOnly: boolean,
): { open: number; waiting: number } {
  const open = loops.filter((loop) => !isFinished(loop.stage));
  return {
    open: open.length,
    waiting: readOnly ? 0 : open.filter((loop) => loopNextAction(loop).decision).length,
  };
}
