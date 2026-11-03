import { Badge } from "@/components/ui/badge";
import type { ActivityEntry } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/** The card's twelve most recent activity entries. */
export function CardHistory({ entries }: { entries: ActivityEntry[] }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">History</h3>
      <ul className="flex flex-col gap-1 text-xs text-[var(--muted-foreground)]">
        {entries.slice(0, 12).map((entry) => (
          <li key={entry.id} className="flex gap-2">
            <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
              {entry.actor_type}
            </Badge>
            <span className="text-[var(--foreground)]">{entry.action}</span>
            <span className="ml-auto">{formatDateTime(entry.timestamp)}</span>
          </li>
        ))}
        {entries.length === 0 ? <li>No history yet.</li> : null}
      </ul>
    </section>
  );
}
