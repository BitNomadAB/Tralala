import { ToneMark } from "@/components/ui/chip";
import type { Card } from "@/lib/types";
import { formatDate, formatDateTime } from "@/lib/utils";
import { REPORT_MEANS, unreportedSince } from "./ticketWork";

type Reported = Pick<Card, "unreported_since" | "completed_at">;

/**
 * "No report" on a Kanban card while a key that took the Ticket has not reported on it: the word
 * with a dot that only repeats it, and on hover, for a screen reader too, when the key took it and
 * what counts as a report. Nothing once the Ticket is completed or nothing is owed.
 */
export function NoReportChip({ card }: { card: Reported }) {
  const since = unreportedSince(card);
  if (since === null) return null;
  return (
    <ToneMark
      tone="warning"
      word="No report"
      compact
      title={`Taken by a key on ${formatDate(since)}. ${REPORT_MEANS}`}
    />
  );
}

/**
 * The same in the Ticket's rail, under where the Ticket stands: "No report since" the date and
 * time the key took it, and what counts as a report.
 */
export function NoReportLine({ card }: { card: Reported }) {
  const since = unreportedSince(card);
  if (since === null) return null;
  return (
    <ToneMark
      tone="warning"
      word={`No report since ${formatDateTime(since)}`}
      reason={`Taken by a key. ${REPORT_MEANS}`}
    />
  );
}
