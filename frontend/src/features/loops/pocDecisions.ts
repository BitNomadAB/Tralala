import type { LoopSummary, PocCounts, PocDecision } from "@/lib/types";
import type { LoopNextAction } from "./loopNextAction";

/**
 * The groups of the Decisions tab, in the order a person reviews them (the server's
 * `review_rank`): open ones other work builds on, open ones of kind missing, the other open ones,
 * then the answered ones.
 */
export type PocGroupId = "built_on" | "missing" | "other" | "answered";

export const POC_GROUP_TITLES: Record<PocGroupId, string> = {
  built_on: "Other work builds on these",
  missing: "Missing from a person",
  other: "Other decisions",
  answered: "Answered",
};

const GROUP_ORDER: readonly PocGroupId[] = ["built_on", "missing", "other", "answered"];

/** The most feedback holds, as the server stores it. */
export const POC_FEEDBACK_MAX = 2000;
export const FEEDBACK_FIRST = "Write the feedback first.";

export const POC_EMPTY =
  "An agent writes a POC decision when it takes a choice that can be changed afterwards. Nothing is waiting.";

/** The group a record belongs to by its own status, kind and whether other work builds on it. */
export function naturalGroup(item: Pick<PocDecision, "status" | "built_on" | "kind">): PocGroupId {
  if (item.status !== "open") return "answered";
  if (item.built_on) return "built_on";
  if (item.kind === "missing") return "missing";
  return "other";
}

/** The number a key ends in (`SES-1-POC-007` is 7): the server orders a group by it. */
export function sequenceOf(key: string): number | null {
  const match = /(\d+)$/.exec(key);
  return match?.[1] === undefined ? null : Number(match[1]);
}

export interface PocGroup {
  id: PocGroupId;
  title: string;
  items: PocDecision[];
}

/**
 * The records under their headings, empty groups left out. `kept` holds the records answered on
 * this visit with the group they were answered in: they stay there, so nothing jumps away from
 * the person who just answered it. Inside a group the records keep the server's order, by their
 * number.
 */
export function pocGroups(
  items: readonly PocDecision[],
  kept: ReadonlyMap<string, PocGroupId> = new Map(),
): PocGroup[] {
  const order = (item: PocDecision, index: number) => sequenceOf(item.key) ?? index;
  return GROUP_ORDER.flatMap((id) => {
    const members = items
      .map((item, index) => ({ item, rank: order(item, index) }))
      .filter(({ item }) => (kept.get(item.id) ?? naturalGroup(item)) === id)
      .sort((left, right) => left.rank - right.rank)
      .map(({ item }) => item);
    return members.length > 0 ? [{ id, title: POC_GROUP_TITLES[id], items: members }] : [];
  });
}

/** The line above the groups: how many wait for an answer. */
export function waitingLine(open: number): string {
  if (open === 0) return "Nothing waits for an answer.";
  return open === 1 ? "1 waits for an answer." : `${open} wait for an answer.`;
}

/** "3 POC decisions wait for your review; other work builds on 2 of them." */
export function dueNotice(due: number, builtOn: number | null): string {
  const head = due === 1 ? "1 POC decision waits" : `${due} POC decisions wait`;
  if (builtOn === null || builtOn === 0) return `${head} for your review.`;
  const of = due === 1 ? "it" : builtOn === due ? "all of them" : `${builtOn} of them`;
  return `${head} for your review; other work builds on ${of}.`;
}

/** "1 thing is missing from a person." */
export function missingNotice(missing: number): string {
  return missing === 1
    ? "1 thing is missing from a person."
    : `${missing} things are missing from a person.`;
}

/** The line in the dialogs that close a Loop while records are not answered. */
export function unansweredLine(open: number): string {
  const head =
    open === 1 ? "1 POC decision is not answered." : `${open} POC decisions are not answered.`;
  return `${head} ${open === 1 ? "It" : "They"} cannot be answered once the Loop is closed.`;
}

/** The record's text as the labelled lines of its sign, empty lines left out. */
export function signLines(item: PocDecision): { label: string; text: string }[] {
  const lines =
    item.kind === "missing"
      ? [
          { label: "Missing", text: item.missing },
          { label: "Why it is needed", text: item.reason },
          { label: "How the work went around it", text: item.chosen },
          { label: "Once it is there", text: item.change_path },
        ]
      : [
          { label: "Chosen", text: item.chosen },
          { label: "Why", text: item.reason },
          { label: "Instead of", text: item.alternative },
          { label: "To change it", text: item.change_path },
        ];
  lines.push({ label: "Builds on it", text: item.builds_on });
  return lines.filter((line) => line.text.trim() !== "");
}

/** "Phase 2" or "Phase 2, finished"; null for a record on no planned Ticket. */
export function phaseText(item: Pick<PocDecision, "phase_number" | "phase_complete">) {
  if (item.phase_number === null) return null;
  return item.phase_complete
    ? `Phase ${item.phase_number}, finished`
    : `Phase ${item.phase_number}`;
}

/** Whether a Loop's counts call a person to its Decisions tab: some are due or missing. */
export function pocCalls(counts: PocCounts | undefined): boolean {
  return counts !== undefined && (counts.due > 0 || counts.missing_open > 0);
}

/**
 * The dashboard's row for a Loop whose POC decisions wait for a review or that misses something
 * from a person, leading to its Decisions tab; null when neither.
 */
export function pocAction(summary: LoopSummary): LoopNextAction | null {
  const counts = summary.poc_decisions;
  if (!pocCalls(counts)) return null;
  const parts = [
    counts.due > 0 ? dueNotice(counts.due, null) : null,
    counts.missing_open > 0 ? missingNotice(counts.missing_open) : null,
  ].filter((part): part is string => part !== null);
  return { waiting: parts.join(" "), label: "Review decisions", decision: true, tab: "decisions" };
}
