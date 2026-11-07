import { http } from "msw";
import type { CardDetail, TicketState, WaitingFor, Workplace } from "@/lib/types";
import { apiPath, failure, ok } from "./envelope";
import { BOARD_ID, LOOP_ID, LOOP_PATH, NOW } from "./loops";

export const CARD_ID = "card-1";
/** The card's own API path, e.g. `${CARD_PATH}/wait`. */
export const CARD_PATH = `${LOOP_PATH}/cards/${CARD_ID}`;
/** The actor id the handlers below record as the one who set a wait. */
export const PERSON_ID = "actor-ada";

/** A planned Ticket as the server serializes it with its checklists and comments. */
export function ticketCard(extra: Partial<CardDetail> = {}): CardDetail {
  return {
    id: CARD_ID,
    board_id: BOARD_ID,
    loop_id: LOOP_ID,
    list_id: "list-1",
    title: "Rotate the signing key",
    description: "",
    summary: "",
    summary_source: "",
    summary_stale: false,
    position: 1024,
    priority: "none",
    due_at: null,
    completed_at: null,
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
    version: 3,
    labels: [],
    checklist_total: 0,
    checklist_completed: 0,
    comment_count: 0,
    ticket_key: "SES-1-PH01-001",
    kind: "ticket",
    phase_number: 1,
    required_actor: "any",
    execution_mode: "normal",
    human_action_required: false,
    human_action_reason: "",
    human_instructions: "",
    human_confirmed_at: null,
    acceptance_criteria: [],
    expected_evidence: [],
    ready: true,
    blockers: [],
    downstream_phase_numbers: [],
    plan_item_id: "item-1",
    workplace: "unknown",
    waiting_for: "nothing",
    waiting_reason: "",
    waiting_set_at: null,
    waiting_set_by: null,
    state: "ready",
    needs_person: false,
    checklists: [],
    comments: [],
    ...extra,
  };
}

/** The server's state rule (`ticket_state`): an answerable wait wins over what blocks it. */
function stateOf(card: CardDetail, waitingFor: WaitingFor): TicketState | null {
  if (card.completed_at) return null;
  if (waitingFor === "decision" || waitingFor === "information" || waitingFor === "access") {
    return "needs_input";
  }
  if (waitingFor === "third_party" || !card.ready) return "blocked";
  return "ready";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const WAITS: readonly WaitingFor[] = ["decision", "information", "access", "third_party"];
const WORKPLACES: readonly Workplace[] = ["codebase", "outside", "unknown"];

/**
 * The card read and the three ticket-work routes over one card in `state.card`, which each change
 * updates and answers, with a new version. A stale `version` answers `409 version_conflict` and a
 * wait without a reason `422`, as the server does. `state.bodies` is every JSON body sent, as
 * "METHOD /path" with the body.
 */
export function ticketWorkHandlers(initial: CardDetail) {
  const state = { card: initial, bodies: [] as { route: string; body: unknown }[] };

  async function change(
    request: Request,
    route: string,
    apply: (body: Record<string, unknown>) => Partial<CardDetail> | Response,
  ) {
    const body: unknown = await request.json();
    state.bodies.push({ route, body });
    if (!isRecord(body)) return failure(422, "validation_error", "Expected an object");
    if (body.version !== state.card.version) {
      return failure(409, "version_conflict", "The card changed since it was read");
    }
    const changes = apply(body);
    if (changes instanceof Response) return changes;
    const next = { ...state.card, ...changes, version: state.card.version + 1 };
    state.card = { ...next, state: stateOf(next, next.waiting_for) };
    // A change answers the card without its checklists and comments, as the server does.
    const { checklists, comments, ...card } = state.card;
    return ok(card);
  }

  const handlers = [
    http.get(apiPath(CARD_PATH), () => ok(state.card)),
    http.patch(apiPath(`${CARD_PATH}/workplace`), ({ request }) =>
      change(request, `PATCH ${CARD_PATH}/workplace`, (body) => {
        const workplace = WORKPLACES.find((value) => value === body.workplace);
        return workplace ? { workplace } : failure(422, "validation_error", "Unknown workplace");
      }),
    ),
    http.patch(apiPath(`${CARD_PATH}/wait`), ({ request }) =>
      change(request, `PATCH ${CARD_PATH}/wait`, (body) => {
        const waitingFor = WAITS.find((wait) => wait === body.waiting_for);
        const reason = typeof body.reason === "string" ? body.reason.trim() : "";
        if (!waitingFor || !reason) {
          return failure(422, "validation_error", "A wait needs its kind and a reason");
        }
        return {
          waiting_for: waitingFor,
          waiting_reason: reason,
          waiting_set_at: NOW,
          waiting_set_by: PERSON_ID,
        };
      }),
    ),
    http.post(apiPath(`${CARD_PATH}/wait/clear`), ({ request }) =>
      change(request, `POST ${CARD_PATH}/wait/clear`, () => ({
        waiting_for: "nothing",
        waiting_reason: "",
        waiting_set_at: null,
        waiting_set_by: null,
      })),
    ),
  ];
  return { state, handlers };
}
