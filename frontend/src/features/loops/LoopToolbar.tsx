import { ArrowLeft, History } from "lucide-react";
import { Link } from "react-router-dom";
import type { Board } from "@/lib/types";

/** The line above the Loop's header: back to its board, and the board's history. */
export function LoopToolbar({ board }: { board: Board }) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]"
    >
      <Link to={`/boards/${board.id}`} className="inline-flex items-center gap-1 hover:underline">
        <ArrowLeft size={13} aria-hidden="true" /> {board.name}
      </Link>
      <span aria-hidden="true">·</span>
      <Link
        to={`/boards/${board.id}/history`}
        className="inline-flex items-center gap-1 hover:underline"
      >
        <History size={13} aria-hidden="true" /> History
      </Link>
    </nav>
  );
}
