import { Avatar } from "@/components/ui/avatar";
import type { ActivityEntry } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { historyLine, whoText } from "./ticketText";

/**
 * The Ticket's history as event rows, newest first: whoever did it, what they did and when. A
 * person or an agent the board knows is named; anyone else by what they are.
 */
export function CardHistory({
  entries,
  nameOf,
}: {
  entries: readonly ActivityEntry[];
  /** The name of a person or an agent on the board, or null. */
  nameOf: (actorId: string) => string | null;
}) {
  if (entries.length === 0) {
    return <p className="m-0 text-sm text-[var(--foreground-faint)]">No history yet.</p>;
  }
  return (
    <ul aria-label="History" className="m-0 grid list-none gap-3 p-0">
      {entries.slice(0, 20).map((entry) => {
        const name = nameOf(entry.actor_id);
        return (
          <li
            key={entry.id}
            className="grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2.5 text-sm"
          >
            <Avatar name={name ?? whoText(entry.actor_type)} size="sm" />
            <div>
              {historyLine(entry, name)}
              <div className="text-xs tabular-nums text-[var(--foreground-faint)]">
                {formatDateTime(entry.timestamp)}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
