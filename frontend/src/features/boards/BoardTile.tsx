import { Archive, ArchiveRestore, Copy, Download, Trash2 } from "lucide-react";
import { Chip } from "@/components/ui/chip";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { api } from "@/lib/api";
import type { Board, BoardStatus } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { tileCounts, type BoardSummaries } from "./boardSummaries";

export type BoardLifecycleAction = "archive" | "restore" | "duplicate";

/** The chip a board shows when it is not simply in use; an active board shows none. */
const STATUS_CHIPS: Record<Exclude<BoardStatus, "active">, string> = {
  archived: "Archived",
  maintenance: "In maintenance",
  error: "Needs attention",
  migration_failed: "Migration failed",
};

/** "2 Loops in progress · 1 waits for you", or what stands in for it while it loads. */
function loopWords(board: Board, summaries: BoardSummaries | undefined): string {
  if (summaries === undefined) return "";
  if (summaries.failed) return "Loops could not be read";
  if (summaries.loops === undefined) return "Reading Loops…";
  const { open, waiting } = tileCounts(summaries.loops, board.status !== "active");
  const progress = open === 1 ? "1 Loop in progress" : `${open} Loops in progress`;
  if (open === 0) return "No Loops in progress";
  return waiting === 0
    ? progress
    : `${progress} · ${waiting === 1 ? "1 waits" : `${waiting} wait`} for you`;
}

/**
 * One board on the dashboard, a place to go: its name, one line of description, its Loops in small
 * words and the last change. The lifecycle actions sit in the quiet "more" menu.
 */
export function BoardTile({
  board,
  summaries,
  onOpen,
  onLifecycle,
  onDelete,
}: {
  board: Board;
  summaries: BoardSummaries | undefined;
  onOpen: () => void;
  onLifecycle: (type: BoardLifecycleAction) => void;
  onDelete: () => void;
}) {
  const archived = board.status === "archived";
  const items: MenuItem[] = [
    {
      label: "Duplicate board",
      icon: <Copy size={14} />,
      onSelect: () => onLifecycle("duplicate"),
    },
    {
      label: "Export board",
      icon: <Download size={14} />,
      onSelect: () => window.location.assign(api.exportUrl(board.id)),
    },
    archived
      ? {
          label: "Restore board",
          icon: <ArchiveRestore size={14} />,
          onSelect: () => onLifecycle("restore"),
        }
      : {
          label: "Archive board",
          icon: <Archive size={14} />,
          onSelect: () => onLifecycle("archive"),
        },
    {
      label: "Delete board",
      icon: <Trash2 size={14} />,
      danger: true,
      disabled: !archived,
      hint: archived ? undefined : "Archive the board first",
      onSelect: onDelete,
    },
  ];
  const words = loopWords(board, summaries);

  return (
    <li className="card-surface flex flex-col gap-2 p-4">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onOpen}
              className="truncate text-left text-[15px] font-semibold text-[var(--foreground)] hover:text-[var(--primary)]"
            >
              {board.name}
            </button>
            {board.status === "active" ? null : <Chip>{STATUS_CHIPS[board.status]}</Chip>}
          </div>
          <p className="mt-1 line-clamp-1 text-sm text-[var(--muted-foreground)]">
            {board.description || "No description"}
          </p>
        </div>
        <Menu label={`More actions for ${board.name}`} items={items} />
      </div>
      <p className="mt-auto flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-[var(--foreground-faint)]">
        {words ? <span>{words}</span> : null}
        <span>Updated {formatDate(board.updated_at)}</span>
      </p>
    </li>
  );
}
