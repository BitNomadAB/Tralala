import type { MarkTone } from "@/components/ui/chip";
import { loopPagePath, ticketPagePath } from "@/features/cards/ticketRules";
import type { Discussion, DiscussionPosition, DiscussionSynthesis } from "@/lib/types";

/**
 * The words a person reads about a discussion. A database status, a run state or a stop code is
 * never shown outside Raw text; every sentence the view shows for one is here, with its test.
 */

const POSITION_LABELS: Record<DiscussionPosition, string> = {
  yes: "Yes",
  yes_with_conditions: "Yes, with conditions",
  no: "No",
  unclear: "Unclear",
};

const POSITION_TONES: Record<DiscussionPosition, MarkTone> = {
  yes: "success",
  yes_with_conditions: "warning",
  no: "danger",
  unclear: "neutral",
};

function isPosition(value: string): value is DiscussionPosition {
  return value in POSITION_LABELS;
}

/** A position or a verdict as a person reads it; a value from before the standard reads Unclear. */
export function positionLabel(position: string): string {
  return isPosition(position) ? POSITION_LABELS[position] : POSITION_LABELS.unclear;
}

/** The mark in front of a position: go, go with care, stop, cannot tell. */
export function positionTone(position: string): MarkTone {
  return isPosition(position) ? POSITION_TONES[position] : POSITION_TONES.unclear;
}

const CONFIDENCE: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

/** "High confidence", or null when the answer gave none. */
export function confidenceText(confidence: string | null): string | null {
  return confidence === null ? null : (CONFIDENCE[confidence] ?? null);
}

/** "1 agent", "3 agents". */
export function countText(count: number, word: string): string {
  return `${String(count)} ${word}${count === 1 ? "" : "s"}`;
}

/** Thousands apart by a space that never breaks, as the rail shows a token count: 12 400. */
export function tokensText(tokens: number): string {
  return String(tokens).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
}

/** "2 of 4": the rounds the thread has had, out of the most it may have. */
export function roundsText(discussion: Discussion): string {
  return `${String(discussion.round_count)} of ${String(discussion.max_rounds)}`;
}

/** The line under the question: "Asked by Mike · 3 agents · round 2 of 4". */
export function askedLine(discussion: Discussion): string {
  const rounds = discussion.round_count === 0 ? "no round yet" : `round ${roundsText(discussion)}`;
  return `Asked by ${discussion.created_by_name} · ${countText(
    discussion.participants.length,
    "agent",
  )} · ${rounds}`;
}

/** Decided for good: no decision, no reply and no run follows. */
export function isClosed(discussion: Discussion): boolean {
  return ["approved", "vetoed", "cancelled"].includes(discussion.status);
}

const REVIEWABLE = ["discussing", "consensus_proposed", "human_review"];

/** Why the decision buttons cannot be pressed now, or null when they can (the server's rule). */
export function decisionBlocked(discussion: Discussion): string | null {
  if (discussion.status === "cancelled") return "The discussion was cancelled";
  if (isClosed(discussion)) return "The discussion is decided";
  if (discussion.run_state === "running") return "The agents are still answering";
  if (discussion.run_state === "paused" || discussion.active_run) {
    return "Stop the run before you decide";
  }
  if (discussion.status === "rework_requested") return "Ask again first: you asked for rework";
  if (!discussion.synthesis || !REVIEWABLE.includes(discussion.status)) {
    return "There is no answer to decide on yet";
  }
  return null;
}

/** Whether Approve, Request rework and Veto may be pressed. */
export function decisionAllowed(discussion: Discussion): boolean {
  return decisionBlocked(discussion) === null;
}

export interface DiscussionState {
  word: string;
  reason: string | null;
  tone: MarkTone;
}

/** Who took a decision or stopped a run, where the caller knows it. */
export interface StateNames {
  decidedBy?: string | null | undefined;
  stoppedBy?: string | null | undefined;
}

function by(word: string, name: string | null | undefined): string {
  return name ? `${word} by ${name}` : word;
}

/**
 * Where a discussion stands, in the words of the rail's Status and the sign: decided, the agents
 * answering, paused or stopped, waiting for the person's decision, or no answer yet.
 */
export function stateOf(discussion: Discussion, names: StateNames = {}): DiscussionState {
  const { status, run_state: run } = discussion;
  if (status === "cancelled") return { word: "Cancelled", reason: null, tone: "neutral" };
  if (status === "approved") {
    return { word: by("Approved", names.decidedBy), reason: null, tone: "success" };
  }
  if (status === "vetoed") {
    return { word: by("Vetoed", names.decidedBy), reason: null, tone: "danger" };
  }
  if (run === "running") {
    const round = Math.min(discussion.round_count + 1, discussion.max_rounds);
    return {
      word: "Agents are answering",
      reason: `round ${String(round)} of ${String(discussion.max_rounds)}`,
      tone: "neutral",
    };
  }
  if (run === "paused") return { word: "Paused", reason: null, tone: "neutral" };
  if (run === "stopped") {
    return { word: by("Stopped", names.stoppedBy), reason: null, tone: "neutral" };
  }
  if (status === "rework_requested") {
    return { word: by("Rework requested", names.decidedBy), reason: null, tone: "warning" };
  }
  if (discussion.synthesis) {
    return {
      word: "Waits for your decision",
      reason: `after round ${String(discussion.synthesis.thread_round)}`,
      tone: "warning",
    };
  }
  return { word: "No answer yet", reason: null, tone: "neutral" };
}

/** The discussion as a page of its Ticket, where "Open as page" and "Copy link" go. */
export function discussionPagePath(
  boardId: string,
  loopId: string,
  cardId: string,
  discussionId: string,
): string {
  return `${ticketPagePath(boardId, loopId, cardId)}/discussions/${encodeURIComponent(discussionId)}`;
}

/** The Ticket over the Kanban (`?card=`), where the rail's Ticket fact leads. */
export function ticketOnLoopPath(boardId: string, loopId: string, cardId: string): string {
  return `${loopPagePath(boardId, loopId)}?card=${encodeURIComponent(cardId)}`;
}

/** A person's decision on a discussion, as the review endpoint takes it. */
export type ReviewDecision = "approve" | "veto" | "rework";

const REVIEWED: Record<ReviewDecision, string> = {
  approve: "Discussion approved",
  veto: "Discussion vetoed",
  rework: "Rework requested",
};

/** What the toast says once a decision is recorded. */
export function reviewedText(decision: ReviewDecision): string {
  return REVIEWED[decision];
}

/** What the reply's composer says under it; a manual thread answers only when asked by name. */
export function replyHint(discussion: Discussion): string {
  return discussion.mode === "manual"
    ? "Mention @agents to make them answer."
    : `One round per reply. Up to ${String(discussion.max_rounds)} rounds in a discussion.`;
}

/**
 * Who the suggestion could not count on, by name, since its sentence only counts: "Cannot tell
 * yet: Gamma · No answer yet from Beta"; null when every agent took a side.
 */
export function holdOutsLine(synthesis: DiscussionSynthesis): string | null {
  const parts: string[] = [];
  const unclear = synthesis.unclear.map((stance) => stance.participant);
  if (unclear.length > 0) parts.push(`Cannot tell yet: ${unclear.join(", ")}`);
  if (synthesis.missing.length > 0)
    parts.push(`No answer yet from ${synthesis.missing.join(", ")}`);
  return parts.length === 0 ? null : parts.join(" · ");
}
