import type { Board } from "@/lib/types";
import type { BoardSummaries } from "./boardSummaries";
import { BoardTile, type BoardLifecycleAction } from "./BoardTile";

/**
 * A named grid of board tiles. The dashboard shows two: the boards in use ("Boards") and, under a
 * heading of their own, the archived ones ("Archived boards").
 */
export function BoardGrid({
  label,
  boards,
  summaries,
  onLifecycle,
  onDelete,
}: {
  /** The list's accessible name. */
  label: string;
  boards: readonly Board[];
  summaries: ReadonlyMap<string, BoardSummaries>;
  onLifecycle: (type: BoardLifecycleAction, board: Board) => void;
  onDelete: (board: Board) => void;
}) {
  return (
    <ul aria-label={label} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {boards.map((board) => (
        <BoardTile
          key={board.id}
          board={board}
          summaries={summaries.get(board.id)}
          onLifecycle={(type) => onLifecycle(type, board)}
          onDelete={() => onDelete(board)}
        />
      ))}
    </ul>
  );
}
