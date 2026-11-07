import { Badge } from "@/components/ui/badge";
import type { DiscussionPoint, DiscussionStance, DiscussionSynthesis } from "@/lib/types";
import { positionLabel, positionTone } from "./positions";

function Stances({ title, stances }: { title: string; stances: DiscussionStance[] }) {
  if (stances.length === 0) return null;
  return (
    <div className="mt-1.5">
      <p className="text-[11px] font-medium text-[var(--muted-foreground)]">{title}</p>
      <ul className="mt-0.5 space-y-0.5 text-xs">
        {stances.map((stance) => (
          <li key={stance.participant_id}>
            <span className="font-medium">{stance.participant}</span> (
            {positionLabel(stance.position)}
            {stance.confidence ? `, ${stance.confidence} confidence` : ""})
            {stance.recommendation ? `: ${stance.recommendation}` : ": answered in prose only"}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Points({ title, points }: { title: string; points: DiscussionPoint[] }) {
  if (points.length === 0) return null;
  return (
    <div className="mt-1.5">
      <p className="text-[11px] font-medium text-[var(--muted-foreground)]">{title}</p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-xs">
        {points.map((point) => (
          <li key={point.text}>
            {point.text}{" "}
            <span className="text-[var(--muted-foreground)]">
              ({point.participants.join(", ")})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Tralala's decision support for the newest round: the suggestion, who stands where with each
 * one's recommendation, the conditions and the open questions. It is labelled a suggestion; the
 * person decides with the buttons under it.
 */
export function DiscussionSynthesisPanel({ synthesis }: { synthesis: DiscussionSynthesis }) {
  const { suggestion } = synthesis;
  return (
    <section
      aria-label="Decision support"
      className="mt-2 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-2"
    >
      <p className="text-[11px] text-[var(--muted-foreground)]">
        Decision support — Tralala&apos;s summary of the answers after round{" "}
        {synthesis.thread_round}. A suggestion, not a decision.
      </p>
      <p className="mt-1 text-sm">
        <span className="font-medium">Suggestion:</span>{" "}
        <Badge tone={positionTone(suggestion.verdict)}>{positionLabel(suggestion.verdict)}</Badge>{" "}
        {suggestion.reason}
      </p>
      <Stances title="For going ahead" stances={synthesis.go} />
      <Stances title="Against" stances={synthesis.stop} />
      <Stances title="Cannot tell yet" stances={synthesis.unclear} />
      <Points title="Conditions to accept if you go ahead" points={synthesis.conditions} />
      <Points title="Open questions" points={synthesis.open_questions} />
      {synthesis.missing.length > 0 ? (
        <p className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
          No answer yet from {synthesis.missing.join(", ")}.
        </p>
      ) : null}
    </section>
  );
}
