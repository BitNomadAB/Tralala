import { Expander } from "@/components/ui/expander";
import type { DiscussionPoint } from "@/lib/types";
import type { RoundLine } from "./discussionData";

/** A condition or an open question, with the agents who named it after it, faint. */
function PointList({ label, points }: { label: string; points: readonly DiscussionPoint[] }) {
  return (
    <ul aria-label={label} className="m-0 grid list-none gap-2 p-0 text-[14.5px]">
      {points.map((point, index) => (
        <li key={index}>
          {point.text}{" "}
          <span className="ml-1 text-[12.5px] text-[var(--foreground-faint)]">
            {point.participants.join(", ")}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The sections under the rows that open on request: the conditions to accept if the person goes
 * ahead and the open questions, each with who said it (absent when there are none), and the
 * rounds, one line each.
 */
export function DiscussionExpanders({
  conditions,
  openQuestions,
  rounds,
  roundsHint,
}: {
  conditions: readonly DiscussionPoint[];
  openQuestions: readonly DiscussionPoint[];
  rounds: readonly RoundLine[];
  /** "2 of 4". */
  roundsHint: string;
}) {
  if (conditions.length + openQuestions.length + rounds.length === 0) return null;
  return (
    <div className="grid gap-2">
      {conditions.length > 0 ? (
        <Expander title="Conditions to accept if you go ahead" hint={String(conditions.length)}>
          <PointList label="Conditions" points={conditions} />
        </Expander>
      ) : null}
      {openQuestions.length > 0 ? (
        <Expander title="Open questions" hint={String(openQuestions.length)}>
          <PointList label="Open questions" points={openQuestions} />
        </Expander>
      ) : null}
      {rounds.length > 0 ? (
        <Expander title="Rounds" hint={roundsHint}>
          <ol aria-label="Rounds" className="m-0 grid list-none gap-2 p-0 text-[14px]">
            {rounds.map((round) => (
              <li key={round.id} className="grid grid-cols-[72px_minmax(0,1fr)] gap-3">
                <span className="tabular-nums text-[var(--muted-foreground)]">
                  Round {round.number}
                </span>
                <span>{round.text}</span>
              </li>
            ))}
          </ol>
        </Expander>
      ) : null}
    </div>
  );
}
