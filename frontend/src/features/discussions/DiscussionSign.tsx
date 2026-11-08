import { ToneMark } from "@/components/ui/chip";
import type { DiscussionSynthesis } from "@/lib/types";
import { holdOutsLine, positionLabel, positionTone, type DiscussionState } from "./discussionRules";

/** While the agents answer: the state ("Agents are answering · round 2 of 3") and the progress. */
export interface SignActivity {
  state: DiscussionState;
  /** "2 of 3 agents have answered this round", or null while paused. */
  progress: string | null;
}

/**
 * The sign, first under the question: Tralala's verdict as a word with its mark and the one
 * sentence of its reason (which counts the sides and names nobody), who cannot tell or has not
 * answered by name, and the faint line that says it is a suggestion after round r. Before the
 * first answer it says so. While the agents answer it starts with where they are; under it, the
 * latest run's outcome in plain words when there is one worth telling.
 */
export function DiscussionSign({
  synthesis,
  activity,
  outcome,
}: {
  synthesis: DiscussionSynthesis | null;
  activity: SignActivity | null;
  outcome: string | null;
}) {
  const holdOuts = synthesis ? holdOutsLine(synthesis) : null;
  return (
    <>
      <section
        aria-label="Tralala's suggestion"
        className="mt-[18px] grid gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5"
      >
        {activity ? (
          <div className="grid gap-1 border-b border-[var(--border-soft)] pb-2.5 last:border-b-0 last:pb-0">
            <ToneMark
              tone={activity.state.tone}
              word={activity.state.word}
              reason={activity.state.reason ?? undefined}
            />
            {activity.progress ? (
              <p className="m-0 text-[13.5px] tabular-nums text-[var(--muted-foreground)]">
                {activity.progress}
              </p>
            ) : null}
          </div>
        ) : null}
        {synthesis ? (
          <>
            <ToneMark
              tone={positionTone(synthesis.suggestion.verdict)}
              word={positionLabel(synthesis.suggestion.verdict)}
            />
            <p className="m-0 max-w-[60ch] text-[17px] font-medium leading-[1.45]">
              {synthesis.suggestion.reason}
            </p>
            {holdOuts ? (
              <p className="m-0 text-[13.5px] text-[var(--muted-foreground)]">{holdOuts}</p>
            ) : null}
            <p className="m-0 text-[12.5px] text-[var(--foreground-faint)]">
              Tralala&apos;s summary of the answers after round {synthesis.thread_round}. A
              suggestion, never a decision: you decide below.
            </p>
          </>
        ) : activity ? null : (
          <ToneMark tone="neutral" word="No answer yet" />
        )}
      </section>
      {outcome ? (
        <p className="m-0 mt-2 text-[13.5px] text-[var(--muted-foreground)]">{outcome}</p>
      ) : null}
    </>
  );
}
