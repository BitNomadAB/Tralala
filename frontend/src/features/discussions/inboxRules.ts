import type { MarkTone } from "@/components/ui/chip";
import type { DiscussionInboxRow, DiscussionWaitsFor } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { by, countText, discussionPagePath, positionLabel, positionTone } from "./discussionRules";

/**
 * The words of the Discussions inbox and of the dashboard's discussion rows: the sections, the
 * mark, the text at the right, the meta line and where a row leads. Split from
 * `discussionRules.ts`, which holds the words of one discussion.
 */

/** The inbox's sections in order, each with its heading and what it says while empty. */
export const INBOX_GROUPS: readonly {
  waitsFor: DiscussionWaitsFor;
  title: string;
  empty: string;
}[] = [
  {
    waitsFor: "your_decision",
    title: "Waits for your decision",
    empty: "Nothing waits for your decision.",
  },
  { waitsFor: "agents", title: "Agents are talking", empty: "No agents are talking now." },
  { waitsFor: "nobody", title: "Decided", empty: "Nothing decided yet." },
];

/**
 * The mark in front of an inbox row: the round while the agents talk ("Round 2 of 3"), the
 * suggested verdict once there is one, and "No answer yet" before the first round.
 */
export function inboxMark(row: DiscussionInboxRow): { word: string; tone: MarkTone } {
  if (row.waits_for === "agents") {
    const round = Math.min(row.round_count + 1, row.max_rounds);
    return { word: `Round ${String(round)} of ${String(row.max_rounds)}`, tone: "neutral" };
  }
  if (row.verdict) return { word: positionLabel(row.verdict), tone: positionTone(row.verdict) };
  return { word: "No answer yet", tone: "neutral" };
}

const DECIDED: Record<string, string> = {
  approved: "Approved",
  vetoed: "Vetoed",
  rework_requested: "Rework requested",
};

/**
 * The text at the right of an inbox row: when the thread last moved, "Answering now" while the
 * agents answer, and the decision with who took it ("Vetoed by Mike · Nov 7, 2026").
 */
export function inboxAside(row: DiscussionInboxRow): string {
  const when = formatDate(row.last_activity_at);
  if (row.waits_for === "agents") {
    return row.run_state === "paused" ? `Paused · ${when}` : "Answering now";
  }
  if (row.waits_for === "nobody") {
    return `${by(DECIDED[row.status] ?? "Decided", row.decided_by_name)} · ${when}`;
  }
  return when;
}

/**
 * The line under an inbox row: "SES-1-PH01-001 · Session expiry · Platform · 3 agents · 2 for ·
 * 1 against · round 2 of 4". A side nobody took is left out.
 */
export function inboxMeta(row: DiscussionInboxRow): string {
  const parts = [row.ticket_key, row.loop_name, row.board_name].filter((part): part is string =>
    Boolean(part),
  );
  parts.push(countText(row.participant_count, "agent"));
  if (row.counts.go > 0) parts.push(`${String(row.counts.go)} for`);
  if (row.counts.stop > 0) parts.push(`${String(row.counts.stop)} against`);
  if (row.counts.unclear > 0) parts.push(`${String(row.counts.unclear)} cannot tell`);
  parts.push(
    row.round_count === 0
      ? "no round yet"
      : `round ${String(row.round_count)} of ${String(row.max_rounds)}`,
  );
  return parts.join(" · ");
}

/** Where an inbox row leads: the discussion as a page of its Ticket, else the board. */
export function inboxPath(row: DiscussionInboxRow): string {
  if (row.loop_id && row.card_id) {
    return discussionPagePath(row.board_id, row.loop_id, row.card_id, row.discussion_id);
  }
  return `/boards/${encodeURIComponent(row.board_id)}`;
}

/** What the dashboard's "Waits for you" says on a discussion row. */
export const WAITS_ON_DISCUSSION = "Waits for your decision on a discussion";
