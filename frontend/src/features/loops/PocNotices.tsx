import { Button } from "@/components/ui/button";
import { usePocDecisions } from "@/lib/queries";
import type { PocCounts } from "@/lib/types";
import { dueNotice, missingNotice } from "./pocDecisions";

/**
 * Above the Loop's tabs, while POC decisions wait for a review (`counts.due`: the Loop's work is
 * done, or a Phase other work builds on is finished) or something is missing from a person: one
 * line each with the way to the Decisions tab. How many of the due ones other work builds on is
 * read from the records, so it is only asked while some are due. It blocks nothing on the page.
 */
export function PocNotices({
  boardId,
  loopId,
  counts,
  onShow,
}: {
  boardId: string;
  loopId: string;
  /** The Loop summary's counts; undefined until the summary arrives. */
  counts: PocCounts | undefined;
  onShow: () => void;
}) {
  const due = counts?.due ?? 0;
  const missing = counts?.missing_open ?? 0;
  const records = usePocDecisions(boardId, loopId, due > 0);
  if (due === 0 && missing === 0) return null;
  const builtOn = records.data
    ? records.data.items.filter((item) => item.due && item.built_on).length
    : null;

  const line = (text: string, label: string) => (
    <p className="m-0 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span>{text}</span>
      <Button size="sm" variant="outline" onClick={onShow}>
        {label}
      </Button>
    </p>
  );

  return (
    <section
      aria-label="POC decisions"
      className="grid gap-1.5 rounded-lg border border-[var(--warning)] p-2 text-sm text-[var(--foreground)]"
    >
      {due > 0 ? line(dueNotice(due, builtOn), "Review decisions") : null}
      {missing > 0 ? line(missingNotice(missing), "See what is missing") : null}
    </section>
  );
}
