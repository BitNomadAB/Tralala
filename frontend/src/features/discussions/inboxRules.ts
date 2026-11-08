import type { MarkTone } from "@/components/ui/chip";
import { loopPagePath } from "@/features/cards/ticketRules";
import type { Discussion, DiscussionInboxRow, DiscussionWaitsFor } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import {
  by,
  countText,
  discussionPagePath,
  isTalking,
  positionLabel,
  positionTone,
  stateOf,
} from "./discussionRules";

/**
 * The words of the lists of discussions: the Discussions inbox, the dashboard's discussion rows
 * and a Ticket's Discussions tab (the sections, the mark, the text at the right, the meta line
 * and where a row leads), and of asking the agents from a Ticket. Split from
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

/**
 * Who a Ticket's discussion waits for, as the inbox groups it: the agents while a run is running
 * or paused, nobody once it is decided or cancelled, otherwise the person (also before a round).
 */
export function discussionWaitsFor(discussion: Discussion): DiscussionWaitsFor {
  if (isTalking(discussion)) return "agents";
  if (DECIDED[discussion.status] !== undefined || discussion.status === "cancelled") {
    return "nobody";
  }
  return "your_decision";
}

const WAIT_ORDER: Record<DiscussionWaitsFor, number> = { your_decision: 0, agents: 1, nobody: 2 };

/**
 * A Ticket's discussions as its tab lists them: those that wait for a decision first, then those
 * the agents are answering, then the decided ones, each newest activity first.
 */
export function ticketDiscussionsInOrder(discussions: readonly Discussion[]): Discussion[] {
  const time = (discussion: Discussion) => Date.parse(discussion.last_activity_at) || 0;
  return [...discussions].sort(
    (a, b) =>
      WAIT_ORDER[discussionWaitsFor(a)] - WAIT_ORDER[discussionWaitsFor(b)] || time(b) - time(a),
  );
}

/**
 * The mark in front of a row of a Ticket's Discussions tab: the state while the agents answer
 * ("Agents are answering", "Paused"), the suggested verdict once there is one, "No answer yet"
 * before it.
 */
export function ticketDiscussionMark(discussion: Discussion): { word: string; tone: MarkTone } {
  if (isTalking(discussion)) {
    const state = stateOf(discussion);
    return { word: state.word, tone: state.tone };
  }
  const verdict = discussion.synthesis?.suggestion.verdict;
  if (verdict) return { word: positionLabel(verdict), tone: positionTone(verdict) };
  return { word: "No answer yet", tone: "neutral" };
}

/**
 * The text at the right of a row of a Ticket's Discussions tab: "Waits for your decision", who
 * it waits for while the agents talk, or the decision with who took it ("Vetoed by Mike").
 */
export function ticketDiscussionAside(discussion: Discussion): string {
  if (discussion.status === "cancelled") return "Cancelled";
  const waits = discussionWaitsFor(discussion);
  if (waits === "agents") {
    return discussion.run_state === "paused" ? "Waits for you to resume" : "Waits for the agents";
  }
  if (waits === "nobody") {
    return by(DECIDED[discussion.status] ?? "Decided", discussion.decided_by_name);
  }
  return "Waits for your decision";
}

/**
 * The line under a row of a Ticket's Discussions tab: "3 agents · 2 for · 1 against · round 2 of
 * 4 · asked by Mike · Nov 8, 2026". A side nobody took is left out.
 */
export function ticketDiscussionMeta(discussion: Discussion): string {
  const parts = [countText(discussion.participant_count, "agent")];
  const synthesis = discussion.synthesis;
  if (synthesis) {
    if (synthesis.go.length > 0) parts.push(`${String(synthesis.go.length)} for`);
    if (synthesis.stop.length > 0) parts.push(`${String(synthesis.stop.length)} against`);
    if (synthesis.unclear.length > 0) {
      parts.push(`${String(synthesis.unclear.length)} cannot tell`);
    }
  }
  parts.push(
    discussion.round_count === 0
      ? "no round yet"
      : `round ${String(discussion.round_count)} of ${String(discussion.max_rounds)}`,
  );
  parts.push(`asked by ${discussion.created_by_name}`, formatDate(discussion.created_at));
  return parts.join(" · ");
}

/**
 * Where a row of a Ticket's Discussions tab leads: over the Kanban the Ticket's dialog shows it
 * (`?card=` and `?discussion=`); on the Ticket's page, the discussion as a page of its Ticket.
 */
export function ticketDiscussionPath(
  host: "modal" | "page",
  boardId: string,
  loopId: string,
  cardId: string,
  discussionId: string,
): string {
  if (host === "page") return discussionPagePath(boardId, loopId, cardId, discussionId);
  const query = new URLSearchParams({ card: cardId, discussion: discussionId });
  return `${loopPagePath(boardId, loopId)}?${query.toString()}`;
}

/** What a Ticket's Discussions tab says while it has none; on a read-only Ticket, the short form. */
export function noTicketDiscussion(readOnly: boolean): string {
  return readOnly ? "No discussion yet." : "No discussion yet. Ask the agents what they think.";
}

/** What "Ask the agents" says on a board where no agent can answer (the service's sentence). */
export const NO_ASKABLE_AGENT =
  "No agent can answer on this board. Add one in Settings → Agents and select it on the board.";

/** The most agents one discussion may ask (the server's limit). */
export const MOST_ASKED = 12;

/** Why "Ask" cannot be pressed yet, or null when it can. */
export function askBlocked(question: string, selected: number, agents: number): string | null {
  if (agents === 0) return NO_ASKABLE_AGENT;
  if (question.trim() === "") return "Write the question first";
  if (selected === 0) return "Choose at least one agent";
  if (selected > MOST_ASKED) return `Choose at most ${String(MOST_ASKED)} agents`;
  return null;
}

/** The question's first 80 characters, as the thread's title (the server derives none from it). */
export function askTitle(question: string): string {
  const flat = question.replace(/\s+/g, " ").trim();
  return flat.length <= 80 ? flat : `${flat.slice(0, 79).trimEnd()}…`;
}

/** What "Ask" creates: a roundtable on the Ticket with the chosen agents and the default cap. */
export function askRequest(cardId: string, question: string, participantIds: readonly string[]) {
  return {
    card_id: cardId,
    title: askTitle(question),
    goal: question.trim(),
    mode: "roundtable",
    participant_ids: [...participantIds],
  };
}

/** The toast when the discussion was opened but its first round could not start. */
export const ASK_NOT_STARTED = "The agents could not start answering";

/** The one sentence under "Ask the agents". */
export const ASK_SENTENCE =
  "Ask one thing. The agents you choose answer in one round, and you decide what follows.";
