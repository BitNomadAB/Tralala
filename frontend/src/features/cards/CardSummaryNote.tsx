import { Sparkles } from "lucide-react";
import type { Card } from "@/lib/types";

const SOURCE_LABEL: Record<Card["summary_source"], string> = {
  "": "",
  plan: "From the RoadMap",
  person: "Written by a person",
  agent: "Written by an agent",
};

/** What the Ticket is about in a sentence or two, above everything else the dialog shows. */
export function CardSummaryNote({ card }: { card: Card }) {
  if (!card.summary) return null;
  return (
    <section
      aria-label="Summary"
      className="flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
        <Sparkles size={12} aria-hidden="true" />
        <span className="font-semibold text-[var(--foreground)]">Summary</span>
        {SOURCE_LABEL[card.summary_source] ? (
          <span>{SOURCE_LABEL[card.summary_source]}</span>
        ) : null}
      </div>
      <p className="text-sm">{card.summary}</p>
      {card.summary_stale ? (
        <p className="text-[11px] text-[var(--warning)]">
          The Ticket changed after this summary was written; it may be out of date.
        </p>
      ) : null}
    </section>
  );
}
