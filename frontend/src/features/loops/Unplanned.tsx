import { useReadiness } from "@/lib/queries";
import { openUnplanned } from "./loopUi";

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
