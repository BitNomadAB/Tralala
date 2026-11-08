import { ToneMark } from "@/components/ui/chip";
import type { DiscussionSynthesis } from "@/lib/types";
import { holdOutsLine, positionLabel, positionTone } from "./discussionRules";

/**
 * The sign, first under the question: Tralala's verdict as a word with its mark and the one
 * sentence of its reason (which counts the sides and names nobody), who cannot tell or has not
 * answered by name, and the faint line that says it is a suggestion after round r. Before the
 * first answer it says so.
 */
export function DiscussionSign({ synthesis }: { synthesis: DiscussionSynthesis | null }) {
  const holdOuts = synthesis ? holdOutsLine(synthesis) : null;
  return (
    <section
      aria-label="Tralala's suggestion"
      className="mt-[18px] grid gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3.5"
    >
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
      ) : (
        <ToneMark tone="neutral" word="No answer yet" />
      )}
    </section>
  );
}
