import { http } from "msw";
import type {
  Discussion,
  DiscussionAnswer,
  DiscussionEvent,
  DiscussionMessage,
  DiscussionParticipant,
  DiscussionPosition,
  DiscussionRun,
  DiscussionStance,
  DiscussionSynthesis,
} from "@/lib/types";
import { CARD_ID, isRecord } from "./cards";
import { apiPath, ok } from "./envelope";
import { BOARD_ID, LOOP, LOOP_ID } from "./loops";
import { MEMBER } from "./session";

export const DISCUSSION_ID = "discussion-1";
export const DISCUSSION_PATH = `/boards/${BOARD_ID}/discussions/${DISCUSSION_ID}`;
export const QUESTION = "Should the agent write the assumption for a skipped question?";
export const TICKET_KEY = "SES-1-PH01-001";
export const REASON =
  "Not settled yet: 2 for going ahead and 1 cannot tell; read the open questions.";
export const REASONING = "From a product view the fix is `reset_scope` in services/loops.py.";
export const REPLY =
  "What if the assumption turns out wrong later in the plan and nobody notices it?";

function at(minute: number): string {
  return `2026-11-08T10:${String(minute).padStart(2, "0")}:00Z`;
}

function participant(name: string, role: string | null): DiscussionParticipant {
  return {
    id: `p-${name}`,
    participant_id: `agent-${name}`,
    participant_type: "agent",
    display_name: name,
    role_template_name: role,
    role_source: "template",
    system_prompt_sha256: "0".repeat(64),
    snapshot_at: at(0),
  };
}

export function answer(changes: Partial<DiscussionAnswer> = {}): DiscussionAnswer {
  return {
    version: 1,
    format: "structured",
    position: "yes",
    recommendation: "Store the assumption with the question.",
    pros: ["Nobody waits on a question only the agent can answer."],
    cons: ["An agent may assume what the person would never choose."],
    conditions: ["The person sees the assumption first."],
    open_questions: [],
    confidence: "medium",
    problem: null,
    ...changes,
  };
}

function person(id: string, actorId: string, name: string, content: string, minute: number) {
  return agentMessage(id, actorId, name, content, null, 0, minute, "user");
}

function agentMessage(
  id: string,
  actorId: string,
  name: string,
  content: string,
  structured: DiscussionAnswer | null,
  round: number,
  minute: number,
  type = "agent",
): DiscussionMessage {
  return {
    id,
    parent_message_id: null,
    author_actor_id: actorId,
    author_type: type,
    author_name: name,
    author_role: type === "agent" ? `${name}'s role` : null,
    content,
    status: "posted",
    model: null,
    round_number: round,
    created_at: at(minute),
    answer: structured,
  };
}

function stance(name: string, message: DiscussionMessage): DiscussionStance {
  const given = message.answer ?? answer();
  return {
    participant_id: `agent-${name}`,
    participant: name,
    position: given.position,
    recommendation: given.recommendation,
    confidence: given.confidence,
    format: given.format,
    message_id: message.id,
    round_number: message.round_number,
  };
}

function synthesis(round: number, verdict: DiscussionPosition): DiscussionSynthesis {
  return {
    version: 1,
    kind: "decision_support",
    written_by: "tralala",
    round_number: 1,
    thread_round: round,
    suggestion: { verdict, reason: REASON },
    counts: { yes: 1, yes_with_conditions: 1, no: 0, unclear: 1, missing: 1 },
    go: [],
    stop: [],
    unclear: [],
    conditions: [],
    open_questions: [],
    missing: [],
  };
}

function run(
  id: string,
  round: number,
  minute: number,
  verdict: DiscussionPosition,
): DiscussionRun {
  return {
    id,
    discussion_id: DISCUSSION_ID,
    status: "completed",
    autonomy: false,
    rounds_requested: 1,
    rounds_completed: 1,
    token_budget: null,
    tokens_used: 6200,
    time_budget_seconds: null,
    elapsed_ms: 24000,
    stop_reason: "rounds_completed",
    error: null,
    started_by_name: MEMBER.name,
    created_at: at(minute - 1),
    started_at: at(minute - 1),
    finished_at: at(minute),
    rounds: [
      {
        id: `${id}-round`,
        run_id: id,
        round_number: 1,
        status: "completed",
        answers: 3,
        failures: 0,
        repeats: 0,
        tokens_used: 6200,
        elapsed_ms: 24000,
        created_at: at(minute),
        finished_at: at(minute),
        synthesis: synthesis(round, verdict),
      },
    ],
  };
}

const ALPHA_1 = agentMessage(
  "m-alpha-1",
  "agent-Alpha",
  "Alpha",
  "First thoughts.",
  answer(),
  1,
  1,
);
const BRAVO_1 = agentMessage("m-bravo-1", "agent-Bravo", "Bravo", "Bravo's prose.", answer(), 1, 1);
const CHARLIE_1 = agentMessage(
  "m-charlie-1",
  "agent-Charlie",
  "Charlie",
  "I would rather wait for the export owner.",
  answer({
    format: "prose",
    position: "unclear",
    recommendation: "",
    pros: [],
    cons: [],
    conditions: [],
    confidence: null,
    problem: "the answer holds no JSON object",
  }),
  1,
  1,
);
const ALPHA_2 = agentMessage(
  "m-alpha-2",
  "agent-Alpha",
  "Alpha",
  REASONING,
  answer({
    position: "yes_with_conditions",
    recommendation:
      "Let the agent write it, but show it to the person before the analysis goes on.",
    pros: ["The approval covers the assumption in writing.", "Nobody waits."],
    cons: ["It may read as the person's decision."],
    conditions: ["The person sees the assumption first."],
    open_questions: ["Who rewrites a wrong assumption?"],
    confidence: "high",
  }),
  2,
  6,
);

/** A discussion two rounds in: four agents, one in prose only, one with no answer yet. */
export function discussion(extra: Partial<Discussion> = {}): Discussion {
  const messages = [
    person("m-question", MEMBER.id, MEMBER.name, QUESTION, 0),
    ALPHA_1,
    BRAVO_1,
    CHARLIE_1,
    person("m-reply", "user-2", "Grace Hopper", REPLY, 5),
    ALPHA_2,
  ];
  return {
    id: DISCUSSION_ID,
    card_id: CARD_ID,
    card_title: "Rotate the signing key",
    ticket_key: TICKET_KEY,
    loop_id: LOOP_ID,
    loop_key: LOOP.key,
    loop_name: LOOP.name,
    title: "Rotate the signing key — discussion",
    goal: QUESTION,
    mode: "roundtable",
    status: "discussing",
    run_state: "idle",
    created_by_name: MEMBER.name,
    max_rounds: 4,
    round_count: 2,
    tokens_used: 12400,
    elapsed_ms: 48000,
    created_at: at(0),
    updated_at: at(7),
    last_activity_at: at(7),
    participant_count: 4,
    message_count: messages.length,
    participants: [
      participant("Alpha", "Product Owner"),
      participant("Bravo", "Backend Developer"),
      participant("Charlie", "QA Engineer"),
      participant("Delta", null),
    ],
    messages,
    active_run: null,
    runs: [run("run-2", 2, 7, "yes_with_conditions"), run("run-1", 1, 2, "unclear")],
    synthesis: {
      ...synthesis(2, "yes_with_conditions"),
      unclear: [stance("Charlie", CHARLIE_1)],
      missing: ["Delta"],
      conditions: [
        { text: "The person sees the assumption first.", participants: ["Alpha", "Bravo"] },
      ],
      open_questions: [{ text: "Who rewrites a wrong assumption?", participants: ["Alpha"] }],
    },
    positions: [stance("Alpha", ALPHA_2), stance("Bravo", BRAVO_1), stance("Charlie", CHARLIE_1)],
    votes: [],
    ...extra,
  };
}

/**
 * What the discussion's API answers and has been sent: the thread, its stored events, every write
 * in `bodies`, and in `next` the thread a write turns it into, by route ("messages", "start",
 * "pause", "resume", "stop").
 */
export interface DiscussionApiState {
  discussion: Discussion;
  events: DiscussionEvent[];
  bodies: { route: string; body: unknown; csrf: string | null }[];
  next: Partial<Record<string, Discussion>>;
}

/** The thread after a write to `route`: what the test set in `next`, or as it was. */
export function after(state: DiscussionApiState, route: string): Discussion {
  state.discussion = state.next[route] ?? state.discussion;
  return state.discussion;
}

/** The discussion's API: the thread, its events, the review and the reply. */
export function discussionHandlers(initial: Discussion = discussion()) {
  const state: DiscussionApiState = { discussion: initial, events: [], bodies: [], next: {} };
  const handlers = [
    http.get(apiPath(DISCUSSION_PATH), () => ok(state.discussion)),
    http.get(apiPath(`${DISCUSSION_PATH}/events/history`), () =>
      ok({ items: state.events, total: state.events.length }),
    ),
    http.post(apiPath(`${DISCUSSION_PATH}/review`), async ({ request }) => {
      const body: unknown = await request.json();
      state.bodies.push({ route: "review", body, csrf: request.headers.get("X-CSRF-Token") });
      const status = isRecord(body) && body.decision === "approve" ? "approved" : "vetoed";
      state.discussion = { ...state.discussion, status };
      return ok(state.discussion);
    }),
    http.post(apiPath(`${DISCUSSION_PATH}/messages`), async ({ request }) => {
      const body: unknown = await request.json();
      state.bodies.push({ route: "messages", body, csrf: request.headers.get("X-CSRF-Token") });
      const thread = after(state, "messages");
      // The server answers every reply on a roundtable thread; a manual one leaves it to the UI.
      return ok({ ...thread, auto_run: thread.mode === "manual" ? null : "started" });
    }),
  ];
  return { state, handlers };
}
