import type { Discussion, DiscussionEvent, DiscussionRun } from "@/lib/types";

/**
 * What the run engine's events say that the thread itself does not: how many agents have answered
 * the round under way, which agents could not be reached in the latest round, and who stopped a
 * run. The events are the engine's JSON, read field by field; a field that is missing or of
 * another type reads as absent.
 */

function text(event: DiscussionEvent, field: string): string | null {
  const value = event.payload[field];
  return typeof value === "string" ? value : null;
}

/** Each run's events, by run id: from its `run_started` up to the next run's, oldest first. */
export function eventsByRun(events: readonly DiscussionEvent[]): Map<string, DiscussionEvent[]> {
  const runs = new Map<string, DiscussionEvent[]>();
  let current: DiscussionEvent[] | null = null;
  for (const event of events.slice().sort((a, b) => a.seq - b.seq)) {
    if (event.type === "run_started") {
      const runId = text(event, "run_id");
      current = runId === null ? null : [];
      if (runId !== null && current !== null) runs.set(runId, current);
    }
    current?.push(event);
  }
  return runs;
}

/** A run's events cut into rounds; each block ends with its `round_completed`, the last may not. */
function rounds(events: readonly DiscussionEvent[]): DiscussionEvent[][] {
  const blocks: DiscussionEvent[][] = [[]];
  for (const event of events) {
    blocks[blocks.length - 1]?.push(event);
    if (event.type === "round_completed") blocks.push([]);
  }
  return blocks;
}

const AGENT_EVENTS = new Set(["agent_started", "agent_completed", "agent_failed"]);

/** The round under way, or once none is, the last round the run completed. */
function latestRound(events: readonly DiscussionEvent[]): DiscussionEvent[] {
  const blocks = rounds(events);
  const last = blocks.at(-1) ?? [];
  if (last.some((event) => AGENT_EVENTS.has(event.type))) return last;
  return blocks.at(-2) ?? [];
}

/** An agent the engine could not get an answer from, with the code it gave (for Raw text). */
export interface RunFailure {
  participantId: string | null;
  name: string;
  error: string;
  round: number | null;
}

function failure(event: DiscussionEvent): RunFailure {
  const round = event.payload.round_number;
  return {
    participantId: text(event, "participant_id"),
    name: text(event, "agent") ?? "An agent",
    error: text(event, "error") ?? "unknown",
    round: typeof round === "number" ? round : null,
  };
}

/** Every agent that failed in a run, in the order it failed. */
export function runFailures(events: readonly DiscussionEvent[]): RunFailure[] {
  return events.filter((event) => event.type === "agent_failed").map(failure);
}

/** The newest run: the one under way, or else the last one the thread had. */
export function latestRun(discussion: Discussion): DiscussionRun | null {
  return discussion.active_run ?? discussion.runs?.[0] ?? null;
}

export interface RunView {
  /** The newest run, or null before the first. */
  run: DiscussionRun | null;
  /** Agents that have answered the round under way. */
  answered: number;
  /** The agents that could not be reached in the latest round, by participant id. */
  failed: ReadonlyMap<string, string>;
  /** Who stopped the newest run, when a person did. */
  stoppedBy: string | null;
  /** Each run's failures, by run id, for Raw text. */
  failures: ReadonlyMap<string, RunFailure[]>;
}

/** The thread's runs as the view tells them, from the thread and its events. */
export function runView(discussion: Discussion, events: readonly DiscussionEvent[]): RunView {
  const byRun = eventsByRun(events);
  const run = latestRun(discussion);
  const own = run ? (byRun.get(run.id) ?? []) : [];
  const current = rounds(own).at(-1) ?? [];
  const answered = new Set(
    current
      .filter((event) => event.type === "agent_completed")
      .map((event) => text(event, "participant_id") ?? event.id),
  );
  const failed = new Map<string, string>();
  for (const entry of runFailures(latestRound(own))) {
    if (entry.participantId !== null) failed.set(entry.participantId, entry.name);
  }
  const stop = own.find(
    (event) => event.type === "run_finished" && text(event, "run_status") === "stopped",
  );
  const failures = new Map<string, RunFailure[]>();
  for (const [runId, runEvents] of byRun) failures.set(runId, runFailures(runEvents));
  return {
    run,
    answered: answered.size,
    failed,
    stoppedBy: stop?.actor_name ?? null,
    failures,
  };
}
