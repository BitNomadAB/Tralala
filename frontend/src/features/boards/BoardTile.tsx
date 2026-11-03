import { Archive, ArchiveRestore, Copy, Download, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Board } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export type BoardLifecycleAction = "archive" | "restore" | "duplicate";

/** One board on the dashboard: its counts and dates, and the actions on it. */
export function BoardTile({
  board,
  onOpen,
  onLifecycle,
  onDelete,
}: {
  board: Board;
  onOpen: () => void;
  onLifecycle: (type: BoardLifecycleAction) => void;
  onDelete: () => void;
}) {
  return (
    <li className="card-surface flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <button
            type="button"
            onClick={onOpen}
            className="truncate text-left text-sm font-semibold hover:text-[var(--primary)]"
          >
            {board.name}
          </button>
          <p className="mt-0.5 line-clamp-2 text-xs text-[var(--muted-foreground)]">
            {board.description || "No description"}
          </p>
        </div>
        <Badge
          tone={
            board.status === "active"
              ? "success"
              : board.status === "archived"
                ? "neutral"
                : "danger"
          }
        >
          {board.status}
        </Badge>
      </div>
      <dl className="grid grid-cols-2 gap-1 text-[11px] text-[var(--muted-foreground)]">
        <div>
          <dt className="uppercase tracking-wide">Lists</dt>
          <dd className="text-[var(--foreground)]">{board.list_count}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Cards</dt>
          <dd className="text-[var(--foreground)]">{board.card_count}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Created</dt>
          <dd className="text-[var(--foreground)]">{formatDate(board.created_at)}</dd>
        </div>
        <div>
          <dt className="uppercase tracking-wide">Updated</dt>
          <dd className="text-[var(--foreground)]">{formatDate(board.updated_at)}</dd>
        </div>
      </dl>
      <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-[var(--border)] pt-2">
        <Button size="sm" variant="secondary" onClick={onOpen}>
          Open
        </Button>
        <Button
          size="icon"
          variant="ghost"
          title="Duplicate board"
          aria-label={`Duplicate ${board.name}`}
          onClick={() => onLifecycle("duplicate")}
        >
          <Copy size={14} />
        </Button>
        <a
          href={api.exportUrl(board.id)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
          title="Export board"
          aria-label={`Export ${board.name}`}
        >
          <Download size={14} />
        </a>
        {board.status === "archived" ? (
          <Button
            size="icon"
            variant="ghost"
            title="Restore board"
            aria-label={`Restore ${board.name}`}
            onClick={() => onLifecycle("restore")}
          >
            <ArchiveRestore size={14} />
          </Button>
        ) : (
          <Button
            size="icon"
            variant="ghost"
            title="Archive board"
            aria-label={`Archive ${board.name}`}
            onClick={() => onLifecycle("archive")}
          >
            <Archive size={14} />
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          title="Delete board"
          aria-label={`Delete ${board.name}`}
          disabled={board.status !== "archived"}
          onClick={onDelete}
        >
          <Trash2 size={14} />
        </Button>
      </div>
    </li>
  );
}
