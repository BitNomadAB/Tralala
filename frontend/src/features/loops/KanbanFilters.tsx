import { Search } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import type { Priority } from "@/lib/types";
import type { TicketFilters } from "./useLoopCards";

/** The Kanban's filters: words, a priority, overdue only. The server searches. */
export function KanbanFilters({
  filters,
  onFiltersChange,
}: {
  filters: TicketFilters;
  onFiltersChange: Dispatch<SetStateAction<TicketFilters>>;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <div className="relative">
        <Search
          size={14}
          aria-hidden="true"
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
        variant={filters.overdue ? "primary" : "quiet"}
        onClick={() => onFiltersChange((current) => ({ ...current, overdue: !current.overdue }))}
        aria-pressed={filters.overdue}
      >
        Overdue
      </Button>
    </div>
  );
}
