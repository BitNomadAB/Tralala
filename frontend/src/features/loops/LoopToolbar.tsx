import { ArrowLeft, Download, History, LayoutTemplate, Search } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Board, Priority } from "@/lib/types";

export interface TicketFilters {
  q: string;
  priority: "" | Priority;
  overdue: boolean;
}

/** Links back to the board, the ticket filters and the Loop page's actions. */
export function LoopToolbar({
  board,
  filters,
  onFiltersChange,
  onToggleActivity,
  readOnly,
  onSaveTemplate,
}: {
  board: Board;
  filters: TicketFilters;
  onFiltersChange: Dispatch<SetStateAction<TicketFilters>>;
  onToggleActivity: () => void;
  readOnly: boolean;
  onSaveTemplate: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]">
      <Link to={`/boards/${board.id}`} className="inline-flex items-center gap-1 hover:underline">
        <ArrowLeft size={13} /> {board.name}
      </Link>
      <span aria-hidden>·</span>
      <Link
        to={`/boards/${board.id}/history`}
        className="inline-flex items-center gap-1 hover:underline"
      >
        <History size={13} /> History
      </Link>
      <span className="ml-auto flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
          />
          <Input
            className="h-8 w-44 pl-8"
            placeholder="Filter tickets"
            aria-label="Filter tickets"
            value={filters.q}
            onChange={(event) =>
              onFiltersChange((current) => ({ ...current, q: event.target.value }))
            }
          />
        </div>
        <Select
          aria-label="Filter by priority"
          className="h-8 w-auto"
          value={filters.priority}
          onChange={(event) =>
            onFiltersChange((current) => ({
              ...current,
              priority: event.target.value as Priority | "",
            }))
          }
        >
          <option value="">Any priority</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </Select>
        <Button
          size="sm"
          variant={filters.overdue ? "primary" : "outline"}
          onClick={() => onFiltersChange((current) => ({ ...current, overdue: !current.overdue }))}
          aria-pressed={filters.overdue}
        >
          Overdue
        </Button>
        <Button size="sm" variant="outline" onClick={onToggleActivity}>
          <History size={14} /> Activity
        </Button>
        <Button size="sm" variant="outline" disabled={readOnly} onClick={onSaveTemplate}>
          <LayoutTemplate size={14} /> Save columns as template
        </Button>
        <a
          href={api.exportUrl(board.id)}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-xs text-[var(--foreground)] hover:bg-[var(--surface-raised)]"
        >
          <Download size={14} /> Export board
        </a>
      </span>
    </div>
  );
}
