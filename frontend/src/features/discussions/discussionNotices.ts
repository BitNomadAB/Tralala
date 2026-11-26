import type { Discussion, DiscussionRun } from "@/lib/types";
import { CLOSED_NOTICE, isThreadClosed, REOPENED_NOTICE } from "./closingRules";
import {
  countText,
  failedLine,
  isTalking,
  outcomeLine,
  positionLabel,
  progressLine,
} from "./discussionRules";
import type { RunView } from "./runEvents";

/**
 * What a screen reader is told while a person has a discussion open (WCAG 4.1.3). The view
 * changes by itself as the agents answer, from server events or a refetch; only a change worth
 * hearing is said, never a refetch that changed nothing: a round that starts, another agent that
 * answered, an agent that could not be reached, how a run ended, and the thread closed or opened
 * again, by the person or by someone else. The sign itself is not a
 * live region, so a person is not read the whole sign on every change.
 */

/** What the person's own actions confirm, beside their toasts. */
export const REPLY_SENT = "Reply sent";

/** Once "Let them talk it out" has started the run. */
export function talkStartedNotice(rounds: number): string {
  return `Talk started: the agents answer each other for up to ${countText(rounds, "round")}.`;
}

/** What the notices compare from one look at the thread to the next. */
export interface LiveState {
  discussionId: string;
  /** The newest run, or null before the first. */
  runId: string | null;
  /** A run is under way: the agents answer, or it is paused between rounds. */
  talking: boolean;
  running: boolean;
  /** The round under way while a run is, else null. */
  round: number | null;
  maxRounds: number;
  /** Agents that have answered the round under way. */
  answered: number;
  agents: number;
  /** The newest run's unreachable agents, by run, round and agent, with the agent's name. */
  failures: ReadonlyMap<string, string>;
  /** How the newest run ended, said once it has. */
  ended: string;
  /** Closed by its opener. */
  closed: boolean;
}

/**
 * How a run ended and where that leaves the discussion: "No agent could be reached. Tralala's
 * suggestion after round 2: Unclear." A run that simply answered says so.
 */
export function endedNotice(
  discussion: Discussion,
  run: DiscussionRun | null,
  stoppedBy: string | null,
): string {
  const outcome = run ? outcomeLine(run, stoppedBy) : null;
  const words =
    outcome ?? (run?.stop_reason === "consensus" ? "The agents agree" : "The agents have answered");
  const synthesis = discussion.synthesis;
  if (!synthesis) return `${words}.`;
  return `${words}. Tralala's suggestion after round ${String(synthesis.thread_round)}: ${positionLabel(synthesis.suggestion.verdict)}.`;
}

/** The thread and its events as the notices compare them. */
export function liveState(discussion: Discussion, view: RunView | null): LiveState {
  const run = view?.run ?? null;
  const talking = isTalking(discussion);
  const runId = run?.id ?? null;
  const failures = new Map<string, string>();
  for (const entry of runId === null ? [] : (view?.failures.get(runId) ?? [])) {
    const round = entry.round === null ? "" : String(entry.round);
    failures.set(`${runId ?? ""}:${round}:${entry.participantId ?? entry.name}`, entry.name);
  }
  return {
    discussionId: discussion.id,
    runId,
    talking,
    running: discussion.run_state === "running",
    round: talking ? Math.min(discussion.round_count + 1, discussion.max_rounds) : null,
    maxRounds: discussion.max_rounds,
    answered: view?.answered ?? 0,
    agents: discussion.participants.length,
    failures,
    ended: endedNotice(discussion, run, view?.stoppedBy ?? null),
    closed: isThreadClosed(discussion),
  };
}

/**
 * What to say now that the thread looks like `after`, having looked like `before`: nothing on the
 * first look (the person reads the view itself) or for another discussion. A paused run that goes
 * on says nothing new: the person who resumed it has the toast.
 */
export function discussionNotices(before: LiveState | null, after: LiveState): string[] {
  if (before?.discussionId !== after.discussionId) return [];
  const notices: string[] = [];
  const newRun = after.runId !== before.runId;
  if (after.running && after.round !== null) {
    if (!before.talking || newRun || before.round !== after.round) {
      notices.push(
        `Agents are answering, round ${String(after.round)} of ${String(after.maxRounds)}`,
      );
    } else if (before.running && after.answered > before.answered) {
      notices.push(progressLine(after.answered, after.agents));
    }
  }
  for (const [key, name] of after.failures) {
    if (!before.failures.has(key)) notices.push(failedLine(name));
  }
  // A run that ended between two looks, and one too short to be seen running, both tell the end.
  const ended = !after.talking && (before.talking || (newRun && after.runId !== null));
  if (ended) notices.push(after.ended);
  if (after.closed !== before.closed) notices.push(after.closed ? CLOSED_NOTICE : REOPENED_NOTICE);
  return notices;
}
