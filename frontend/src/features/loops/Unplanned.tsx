import { Check } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useReadiness } from "@/lib/queries";
import type { UnplannedTicket } from "@/lib/types";
import { openUnplanned } from "./loopUi";

/** The plan dialog's list of Tickets added outside the plan while it executes. */
export function OutsideThePlan({ tickets }: { tickets: UnplannedTicket[] }) {
  const shown = tickets.filter((ticket) => !ticket.archived_at);
  if (shown.length === 0) return null;
  return (
    <section
      aria-label="Outside the plan"
      className="mt-3 rounded-lg border border-dashed border-[var(--border)] p-3"
    >
      <h3 className="text-sm font-medium">Outside the plan</h3>
      <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
        Added while the plan runs. These never block a Phase or the Loop&apos;s completion.
      </p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {shown.map((ticket) => (
          <li
            key={ticket.id}
            className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5"
          >
            <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
              {ticket.key ?? "—"}
            </span>
            <span className="text-sm">{ticket.title}</span>
            {ticket.completed_at ? (
              <Badge tone="success">
                <Check size={11} /> done
              </Badge>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The completion dialog's note on open work outside the plan: a warning, never a blocker. */
export function UnplannedWarning({ boardId, loopId }: { boardId: string; loopId: string }) {
  const readiness = useReadiness(boardId, loopId);
  const open = openUnplanned(readiness.data?.unplanned ?? []);
  if (open.length === 0) return null;
  return (
    <p className="text-xs text-[var(--warning)]">
      {open.length} Ticket(s) outside the plan are still open (
      {open.map((ticket) => ticket.key ?? ticket.title).join(", ")}). They do not block acceptance;
      they stay open in the completed Loop.
    </p>
  );
}
