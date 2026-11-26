import type { MarkTone } from "@/components/ui/chip";
import type { Discussion } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { countText, isTalking, positionLabel, positionTone, stateOf } from "./discussionRules";

/**
 * The words of the board's own discussions: the list on the board's page (its filter, its rows
 * and what it says while empty) and "New discussion", which opens one on the board.
 */

export type BoardDiscussionFilter = "open" | "closed";

/** The filter over the board's list: the open threads first, the closed ones on request. */
export const BOARD_DISCUSSION_FILTERS = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
] as const;

/** What the list says while it has nothing to show under the filter. */
export function noBoardDiscussion(filter: BoardDiscussionFilter, readOnly: boolean): string {
  if (filter === "closed") return "No closed discussion on this board.";
  return readOnly
    ? "No open discussion on this board."
    : "No open discussion on this board. Start one with New discussion.";
}

/** The board's threads, newest activity first. */
export function newestFirst(discussions: readonly Discussion[]): Discussion[] {
  const time = (discussion: Discussion) => Date.parse(discussion.last_activity_at) || 0;
  return [...discussions].sort((a, b) => time(b) - time(a));
}

/**
 * The mark in front of a row: Closed, the state while the agents answer, the suggested verdict
 * once there is one; Open for a thread no agent takes part in, which people answer; No answer yet
 * before the agents' first round.
 */
export function boardDiscussionMark(discussion: Discussion): { word: string; tone: MarkTone } {
  if (discussion.status === "closed") return { word: "Closed", tone: "neutral" };
  if (isTalking(discussion)) {
    const state = stateOf(discussion);
    return { word: state.word, tone: state.tone };
  }
  const verdict = discussion.synthesis?.suggestion.verdict;
  if (verdict) return { word: positionLabel(verdict), tone: positionTone(verdict) };
  if (discussion.participant_count === 0) return { word: "Open", tone: "neutral" };
  return { word: "No answer yet", tone: "neutral" };
}

/** The line under a row: "Asked by Mike · 2 agents · 5 messages", or "no agents". */
export function boardDiscussionMeta(discussion: Discussion): string {
  const agents =
    discussion.participant_count === 0
      ? "no agents"
      : countText(discussion.participant_count, "agent");
  return [
    `Asked by ${discussion.created_by_name}`,
    agents,
    countText(discussion.message_count, "message"),
  ].join(" · ");
}

/** The text at the right of a row: when the thread last moved. */
export function boardDiscussionAside(discussion: Discussion): string {
  return formatDate(discussion.last_activity_at);
}

/** The one sentence under "New discussion". */
export const NEW_DISCUSSION_SENTENCE =
  "Ask the board a question that is not about one Ticket. Choose agents to answer in one round, or none to ask the people on the board.";

/** What the dialog says under an empty field when Create is pressed. */
export const NO_TITLE = "Write a title.";
export const NO_QUESTION = "Write the question.";

/**
 * What "New discussion" creates: with agents, a roundtable they answer in a round started at
 * once; without, a question to nobody in particular (`manual`, no round), which people answer.
 */
export function newDiscussionRequest(
  title: string,
  question: string,
  participantIds: readonly string[],
) {
  return {
    title: title.trim(),
    goal: question.trim(),
    mode: participantIds.length > 0 ? "roundtable" : "manual",
    participant_ids: [...participantIds],
  };
}
