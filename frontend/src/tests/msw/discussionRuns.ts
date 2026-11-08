import { http } from "msw";
import type { Discussion, DiscussionEvent, DiscussionRun } from "@/lib/types";
import {
  after,
  discussion,
  DISCUSSION_ID,
  DISCUSSION_PATH,
  type DiscussionApiState,
} from "./discussions";
import { apiPath, ok } from "./envelope";
import { MEMBER } from "./session";

export const RUN_ID = "run-3";
const STARTED = "2026-11-08T10:10:00Z";

/** One stored event of the thread, as the event history replays it. */
export function event(
  seq: number,
  type: string,
  payload: Record<string, unknown> = {},
  actorName: string | null = null,
): DiscussionEvent {
  return {
    seq,
    id: `event-${String(seq)}`,
    discussion_id: DISCUSSION_ID,
    type,
    payload,
    actor_id: actorName === null ? null : MEMBER.id,
    actor_type: actorName === null ? null : "user",
    actor_name: actorName,
    created_at: STARTED,
  };
}

/** The third run of the thread: "Let them talk it out" for two rounds, under way by default. */
export function talkRun(changes: Partial<DiscussionRun> = {}): DiscussionRun {
  return {
    id: RUN_ID,
    discussion_id: DISCUSSION_ID,
    status: "running",
    autonomy: true,
    rounds_requested: 2,
    rounds_completed: 0,
    token_budget: 20000,
    tokens_used: 0,
    time_budget_seconds: 300,
    elapsed_ms: 0,
    stop_reason: null,
    error: null,
    started_by_name: MEMBER.name,
    created_at: STARTED,
    started_at: STARTED,
    finished_at: null,
    rounds: [],
    ...changes,
  };
}

/** The discussion two rounds in with the agents answering round 3 of 4, or paused there. */
export function talking(runState: "running" | "paused" = "running"): Discussion {
  const run = talkRun({ status: runState });
  const base = discussion();
  return { ...base, run_state: runState, active_run: run, runs: [run, ...(base.runs ?? [])] };
}

/** The discussion once the third run ended as `changes` say. */
export function ended(changes: Partial<DiscussionRun>): Discussion {
  const run = talkRun({ finished_at: STARTED, ...changes });
  const base = discussion();
  const runState = changes.status === "stopped" ? "stopped" : "idle";
  return { ...base, run_state: runState, active_run: null, runs: [run, ...(base.runs ?? [])] };
}

function agent(name: string, round = 1) {
  return { participant_id: `agent-${name}`, agent: name, round_number: round };
}

/**
 * The third run's events: started by the member; in its first round Alpha answered, Bravo could
 * not be reached and Charlie is answering.
 */
export function talkEvents(): DiscussionEvent[] {
  return [
    event(1, "run_started", { run_id: RUN_ID, rounds_requested: 2, autonomous: true }, MEMBER.name),
    event(2, "agent_started", agent("Alpha")),
    event(3, "agent_completed", { ...agent("Alpha"), position: "yes" }),
    event(4, "agent_started", agent("Bravo")),
    event(5, "agent_failed", { ...agent("Bravo"), error: "connection_refused" }),
    event(6, "agent_started", agent("Charlie")),
  ];
}

/** What start, pause, resume and stop answer: the run summary, reduced to what the view reads. */
function summary(thread: Discussion) {
  const run = thread.active_run ?? thread.runs?.[0] ?? null;
  return {
    discussion_id: thread.id,
    run_id: run?.id ?? RUN_ID,
    status: thread.status,
    thread_status: thread.status,
    run_state: thread.run_state,
    run_status: run?.status ?? "completed",
    stop_reason: run?.stop_reason ?? null,
    failures: [],
    pending: run?.status === "running",
    run,
  };
}

/** Start and the run controls; each write lands in `bodies` and turns the thread into `next`. */
export function runHandlers(state: DiscussionApiState) {
  return [
    http.post(apiPath(`${DISCUSSION_PATH}/start`), async ({ request }) => {
      const body: unknown = await request.json();
      state.bodies.push({ route: "start", body, csrf: request.headers.get("X-CSRF-Token") });
      return ok(summary(after(state, "start")));
    }),
    http.post(apiPath(`${DISCUSSION_PATH}/runs/:runId/:action`), async ({ request, params }) => {
      const body: unknown = await request.json();
      const runId = typeof params.runId === "string" ? params.runId : "";
      const action = typeof params.action === "string" ? params.action : "";
      state.bodies.push({
        route: `runs/${runId}/${action}`,
        body,
        csrf: request.headers.get("X-CSRF-Token"),
      });
      return ok(summary(after(state, action)));
    }),
  ];
}
