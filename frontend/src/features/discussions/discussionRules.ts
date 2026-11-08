import type { MarkTone } from "@/components/ui/chip";
import { loopPagePath, ticketPagePath } from "@/features/cards/ticketRules";
import type {
  Discussion,
  DiscussionPosition,
  DiscussionRun,
  DiscussionSynthesis,
} from "@/lib/types";

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

export function by(word: string, name: string | null | undefined): string {
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

/** The agents are answering or paused between rounds: a run is under way. */
export function isTalking(discussion: Discussion): boolean {
  return discussion.run_state === "running" || discussion.run_state === "paused";
}

/** What the reply's composer says under it: a reply is a new round, or why it must wait. */
export function replyHint(discussion: Discussion): string {
  return isTalking(discussion)
    ? "The agents are answering. Reply once they are done."
    : "The agents answer in a new round.";
}

/**
 * Whether the UI starts the round a reply asks for: the server starts it itself on a thread that
 * answers every reply (`auto_run` is then set, also when it could not start one), and leaves it
 * to the caller on a thread that answers only when asked.
 */
export function replyNeedsRound(saved: Discussion): boolean {
  return (saved.auto_run ?? null) === null && !isClosed(saved);
}

/** The most rounds one run may ask for (the server's cap). */
export const RUN_ROUNDS = 4;

/** The rounds the discussion has left before it reaches its most. */
export function roundsLeft(discussion: Discussion): number {
  return Math.max(0, discussion.max_rounds - discussion.round_count);
}

/** The rounds "Let them talk it out" offers: the rounds left, at most four. */
export function talkRounds(discussion: Discussion): number {
  return Math.min(roundsLeft(discussion), RUN_ROUNDS);
}

/** Why "Let them talk it out" cannot be pressed now, or null when it can. */
export function talkBlocked(discussion: Discussion): string | null {
  if (discussion.status === "cancelled") return "The discussion was cancelled";
  if (isClosed(discussion)) return "The discussion is decided";
  if (isTalking(discussion)) return "The agents are already answering";
  if (roundsLeft(discussion) === 0) {
    return `No round is left: the discussion has had all ${String(discussion.max_rounds)}`;
  }
  return null;
}

/** The one sentence of the "Let them talk it out" dialog. */
export function talkSentence(rounds: number): string {
  return `The agents answer each other for up to ${countText(
    rounds,
    "round",
  )} and stop when they agree or when the budget is spent.`;
}

/** What "Let them talk it out" sends: the rounds, and a budget only where one was given. */
export interface TalkRequest {
  autonomous: true;
  rounds: number;
  token_budget?: number;
  time_budget_seconds?: number;
}

const WHOLE = /^\d+$/;

function budget(value: string, most: number): number | null | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return undefined;
  if (!WHOLE.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return parsed <= most ? parsed : null;
}

/** The dialog's fields as the start call takes them, or null while one of them is not valid. */
export function talkRequest(
  fields: { rounds: string; tokens: string; seconds: string },
  most: number,
): TalkRequest | null {
  const rounds = budget(fields.rounds, most);
  const tokens = budget(fields.tokens, 5_000_000);
  const seconds = budget(fields.seconds, 3600);
  if (rounds === null || rounds === undefined || rounds < 1) return null;
  if (tokens === null || seconds === null) return null;
  return {
    autonomous: true,
    rounds,
    ...(tokens === undefined ? {} : { token_budget: tokens }),
    ...(seconds === undefined ? {} : { time_budget_seconds: seconds }),
  };
}

/** The progress line while the agents answer: "2 of 3 agents have answered this round". */
export function progressLine(answered: number, agents: number): string {
  const verb = agents === 1 ? "agent has" : "agents have";
  return `${String(answered)} of ${String(agents)} ${verb} answered this round`;
}

/**
 * How a run ended, in plain words; null while it runs. The run's status and stop reason are
 * codes, shown only in Raw text.
 */
export function outcomeWords(run: DiscussionRun, stoppedBy: string | null = null): string | null {
  switch (run.status) {
    case "running":
      return null;
    case "paused":
      return "Paused";
    case "stopped":
      return by("Stopped", stoppedBy);
    case "budget_exhausted":
      return "The budget ran out";
    case "no_progress":
      return "The agents repeated themselves, so the run stopped";
    case "failed":
      if (run.stop_reason === "all_participants_failed") return "No agent could be reached";
      if (run.stop_reason === "process_restart") {
        return "The run broke off when the server restarted";
      }
      return "The run broke off with an error";
    case "completed":
      return run.stop_reason === "consensus" ? "The agents agree" : "Rounds used up";
    default:
      return "The run ended";
  }
}

/**
 * The line under the sign about the latest run, or null: nothing while it runs or is paused (the
 * state says so), when the agents agree (the sign says so), or after one round asked for by a
 * reply, which simply ran.
 */
export function outcomeLine(run: DiscussionRun | null, stoppedBy: string | null): string | null {
  if (run === null || run.status === "running" || run.status === "paused") return null;
  if (run.status === "completed" && (run.stop_reason === "consensus" || !run.autonomy)) {
    return null;
  }
  return outcomeWords(run, stoppedBy);
}

/** Under the row of an agent the latest round could not reach. */
export function failedLine(name: string): string {
  return `No answer from ${name}: the agent could not be reached.`;
}

export type RunAction = "pause" | "resume" | "stop";

/**
 * The run's items under More: Pause while the agents answer, Resume while paused; the rail's More
 * also offers Stop the run (`withStop`), which the actions row shows as its own button.
 */
export function runControls(
  discussion: Discussion,
  withStop = false,
): { action: RunAction; label: string }[] {
  const stop = withStop ? [{ action: "stop" as const, label: "Stop the run" }] : [];
  if (discussion.run_state === "running") {
    return [{ action: "pause", label: "Pause while they talk" }, ...stop];
  }
  if (discussion.run_state === "paused") return [{ action: "resume", label: "Resume" }, ...stop];
  return [];
}

const CONTROLLED: Record<RunAction, string> = {
  pause: "The run is paused",
  resume: "The agents go on",
  stop: "The run is stopped",
};

/** What the toast says once Pause, Resume or Stop is through. */
export function controlledText(action: RunAction): string {
  return CONTROLLED[action];
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
