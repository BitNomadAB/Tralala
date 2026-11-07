import { User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Card } from "@/lib/types";

/** What a planned Ticket carries: its phase, the human action it needs and what blocks it. */
export function CardTicketSummary({ card }: { card: Card }) {
  if (!card.ticket_key && !card.human_action_required && card.blockers.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-[11px]">
      <div className="flex flex-wrap items-center gap-2">
        {card.ticket_key ? (
          <span className="font-mono text-[var(--muted-foreground)]">{card.ticket_key}</span>
        ) : null}
        {card.phase_number ? <Badge tone="neutral">Phase {card.phase_number}</Badge> : null}
        {card.human_action_required ? (
          <Badge tone="warning">
            <User size={11} /> Human action required
          </Badge>
        ) : null}
      </div>
      {card.human_action_required && card.human_action_reason ? (
        <p className="text-[var(--muted-foreground)]">
          Why a human is needed: {card.human_action_reason}
        </p>
      ) : null}
      {card.human_action_required && card.human_instructions ? (
        <p className="text-[var(--muted-foreground)]">What to do: {card.human_instructions}</p>
      ) : null}
      {card.human_action_required && card.downstream_phase_numbers.length > 0 ? (
        <p className="text-[var(--muted-foreground)]">
          Phase {card.downstream_phase_numbers.join(", ")} and its dependent phases cannot start
          until a human confirms this action.
        </p>
      ) : null}
      {!card.ready && card.blockers.length > 0 ? (
        <p className="text-[var(--warning)]">
          Blocked by:{" "}
          {card.blockers
            .map((blocker) =>
              blocker.type === "phase"
                ? `Phase ${blocker.phase_number ?? "?"}`
                : (blocker.key ?? blocker.title ?? "Ticket"),
            )
            .join(", ")}
        </p>
      ) : null}
      {card.acceptance_criteria.length > 0 ? (
        <p className="text-[var(--muted-foreground)]">
          Accepted when: {card.acceptance_criteria.join("; ")}
        </p>
      ) : null}
      {card.expected_evidence.length > 0 ? (
        <p className="text-[var(--muted-foreground)]">
          Evidence: {card.expected_evidence.join("; ")}
        </p>
      ) : null}
    </div>
  );
}
