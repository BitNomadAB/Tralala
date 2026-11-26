import { http } from "msw";
import type { PocCounts, PocDecision, StopList } from "@/lib/types";
import { apiPath, failure, ok } from "./envelope";
import { LOOP, LOOP_ID, LOOP_PATH, NOW } from "./loops";
import { DEFAULT_STOP_LIST } from "./stops";

/** The key and id of the Ticket a feedback answer creates in the handlers below. */
export const FEEDBACK_TICKET = { id: "card-feedback", key: "SES-1-UNP-002" };

/**
 * A POC decision as the server lists it: by default an open plain decision numbered `sequence`,
 * taken on no Ticket; `extra` replaces any field.
 */
export function pocDecision(sequence: number, extra: Partial<PocDecision> = {}): PocDecision {
  const key = `${LOOP.key}-POC-${String(sequence).padStart(3, "0")}`;
  return {
    id: `poc-${sequence}`,
    key,
    loop_id: LOOP_ID,
    card_id: null,
    ticket_key: null,
    ticket_title: null,
    phase_number: null,
    phase_complete: null,
    kind: "decision",
    title: `Decision ${sequence}`,
    chosen: "Sessions end after 30 idle minutes.",
    reason: "It matches the bank's own rule.",
    alternative: "A limit of 15 minutes.",
    change_path: "Change the limit in the settings.",
    missing: "",
    builds_on: "",
    built_on: false,
    details: "",
    status: "open",
    feedback: "",
    feedback_ticket: null,
    due: false,
    created_at: NOW,
    created_by: { name: "worker-key", type: "agent" },
    answered_at: null,
    answered_by_name: null,
    ...extra,
  };
}

/** The group the server reviews a record in (`poc_decision_rules.review_rank`). */
function rank(item: PocDecision): number {
  if (item.status !== "open") return 3;
  if (item.built_on) return 0;
  if (item.kind === "missing") return 1;
  return 2;
}

/** The counts over `items`, as the server counts them. */
export function pocCounts(items: readonly PocDecision[]): PocCounts {
  const open = items.filter((item) => item.status === "open");
  return {
    open: open.length,
    built_on_open: open.filter((item) => item.built_on).length,
    missing_open: open.filter((item) => item.kind === "missing").length,
    due: open.filter((item) => item.due).length,
    answered: items.length - open.length,
  };
}

/**
 * The Loop's POC decisions and stop list: the list in review order with its counts, an answer
 * (feedback creates `FEEDBACK_TICKET`; a record answered with feedback is `409
 * poc_decision_answered`), and the stop list, which a PUT replaces once it keeps the server's
 * rules (`422 stops_invalid` otherwise). `refuseAnswer` makes every answer fail as given.
 * `state.answers` and `state.stopWrites` are the bodies the handlers took.
 */
export function pocHandlers(
  items: PocDecision[],
  options: {
    stops?: StopList;
    refuseAnswer?: { status: number; code: string; message: string };
  } = {},
) {
  const state = {
    items,
    stops: options.stops ?? DEFAULT_STOP_LIST,
    answers: [] as unknown[],
    stopWrites: [] as unknown[],
  };
  const handlers = [
    http.get(apiPath(`${LOOP_PATH}/poc-decisions`), () => {
      const ordered = [...state.items].sort(
        (left, right) => rank(left) - rank(right) || left.key.localeCompare(right.key),
      );
      return ok({ items: ordered, counts: pocCounts(state.items) });
    }),
    http.post(apiPath(`${LOOP_PATH}/poc-decisions/:id/answer`), async ({ request, params }) => {
      const body = (await request.json()) as { answer?: string; feedback?: string };
      state.answers.push(body);
      const refusal = options.refuseAnswer;
      if (refusal) return failure(refusal.status, refusal.code, refusal.message);
      const item = state.items.find((entry) => entry.id === params.id);
      if (!item) return failure(404, "poc_decision_not_found", "POC decision not found");
      if (item.status === "feedback") {
        return failure(
          409,
          "poc_decision_answered",
          "This POC decision was answered with feedback",
        );
      }
      const answered: PocDecision = {
        ...item,
        status: body.answer === "feedback" ? "feedback" : "ok",
        feedback: body.answer === "feedback" ? (body.feedback ?? "") : "",
        feedback_ticket: body.answer === "feedback" ? FEEDBACK_TICKET : null,
        due: false,
        answered_at: NOW,
        answered_by_name: "Ada Member",
      };
      state.items = state.items.map((entry) => (entry.id === item.id ? answered : entry));
      return ok(answered);
    }),
    http.get(apiPath(`${LOOP_PATH}/stops`), () => ok(state.stops)),
    http.put(apiPath(`${LOOP_PATH}/stops`), async ({ request }) => {
      const body = (await request.json()) as { stops: string[] };
      state.stopWrites.push(body);
      const long = body.stops.findIndex((line) => line.length > 140);
      if (body.stops.length > 12 || long >= 0) {
        const problem =
          long >= 0 ? `Line ${long + 1} has more than 140 characters.` : "The list is too long.";
        return failure(422, "stops_invalid", `The stop list is not valid: ${problem}`);
      }
      state.stops = { stops: body.stops, is_default: false };
      return ok(state.stops);
    }),
  ];
  return { state, handlers };
}
