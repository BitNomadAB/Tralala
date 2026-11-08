import { http } from "msw";
import {
  PRIORITIES,
  type ActivityEntry,
  type BoardList,
  type BoardPerson,
  type CardDetail,
  type CardNote,
  type Label,
  type LoopReadiness,
  type Loop,
  type PlanTicketView,
  type TicketFace,
} from "@/lib/types";
import { CARD_ID, CARD_PATH, changeCard, isRecord, ticketCard, ticketWorkHandlers } from "./cards";
import { apiPath, failure, ok, requestPath } from "./envelope";
import { BOARD_ID, LOOP, LOOP_ID, LOOP_PATH, NOW } from "./loops";
import { noteHandlers } from "./notes";
import { MEMBER } from "./session";

function column(id: string, name: string, position: number, count: number): BoardList {
  return {
    id,
    board_id: BOARD_ID,
    loop_id: LOOP_ID,
    name,
    position,
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
    card_count: count,
  };
}

/** The Loop's three columns; the card starts in the first. */
export const COLUMNS: BoardList[] = [
  column("list-1", "Backlog", 0, 13),
  column("list-2", "In Progress", 1, 0),
  column("list-3", "Done", 2, 21),
];

export const LABELS: Label[] = [
  { id: "label-1", name: "Backend", color: "#4b8bf5" },
  { id: "label-2", name: "Security", color: "#e3b341" },
];

/** The board's people: the signed-in member and one more. */
export const PEOPLE: BoardPerson[] = [
  { id: MEMBER.id, name: MEMBER.name, type: "user", role: "member" },
  { id: "user-2", name: "Grace Hopper", type: "user", role: "admin" },
];

export const PHASE_NAME = "Session limits";
export const PREREQUISITE_KEY = "SES-1-PH01-000";

function planItem(id: string, key: string, extra: Partial<PlanTicketView>): PlanTicketView {
  return {
    id,
    key,
    title: key,
    phase_id: "phase-1",
    phase_number: 1,
    objective: "",
    instructions: "",
    required_actor: "any",
    execution_mode: "normal",
    acceptance_criteria: [],
    expected_evidence: [],
    human_action_reason: "",
    human_instructions: "",
    prerequisite_ticket_ids: [],
    prerequisite_phase_ids: [],
    card_id: null,
    completed_at: null,
    ready: true,
    blockers: [],
    human_action_required: false,
    downstream_phase_numbers: [],
    workplace: "unknown",
    waiting_for: "nothing",
    state: "ready",
    ...extra,
  };
}

/** The plan as readiness serves it: the card's item depends on one completed Ticket. */
export const READINESS: LoopReadiness = {
  loop_id: LOOP_ID,
  stage: "in_progress",
  execution_allowed: true,
  blocked_reason: null,
  items: [
    planItem("item-0", PREREQUISITE_KEY, { card_id: "card-0", completed_at: NOW, state: null }),
    planItem("item-1", "SES-1-PH01-001", { card_id: CARD_ID, prerequisite_ticket_ids: ["item-0"] }),
  ],
  phases: [
    {
      id: "phase-1",
      number: 1,
      name: PHASE_NAME,
      objective: "",
      entry_conditions: [],
      exit_conditions: [],
      prerequisite_phase_ids: [],
      prerequisite_ticket_ids: [],
      state: "active",
      blocked_by: [],
      tickets: [],
    },
  ],
  unplanned: [],
};

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

/** The face a `PATCH` gives (the server checks it whole), or undefined when it gives none. */
function patchedFace(body: Record<string, unknown>): TicketFace | undefined {
  const given = ["why", "if_skipped", "pros", "cons", "steps"].some((name) => name in body);
  if (!given) return undefined;
  return {
    summary: typeof body.summary === "string" ? body.summary : "",
    why: typeof body.why === "string" ? body.why : "",
    if_skipped: typeof body.if_skipped === "string" ? body.if_skipped : "",
    pros: strings(body.pros),
    cons: strings(body.cons),
    steps: strings(body.steps),
  };
}

/** The fields of a card `PATCH` the server applies, as the card they change. */
function patched(body: Record<string, unknown>): Partial<CardDetail> {
  const changes: Partial<CardDetail> = {};
  const face = patchedFace(body);
  if (face) changes.face = face;
  if (typeof body.summary === "string") changes.summary = body.summary;
  if (typeof body.title === "string") changes.title = body.title;
  if (typeof body.description === "string") changes.description = body.description;
  const priority = PRIORITIES.find((value) => value === body.priority);
  if (priority) changes.priority = priority;
  if (typeof body.due_at === "string") changes.due_at = body.due_at;
  if (body.clear_due_at === true) changes.due_at = null;
  const ids = body.labels;
  if (Array.isArray(ids)) changes.labels = LABELS.filter((label) => ids.includes(label.id));
  if (typeof body.assignee_actor_id === "string") {
    const person = PEOPLE.find((candidate) => candidate.id === body.assignee_actor_id);
    changes.assignee_actor_id = body.assignee_actor_id;
    changes.assignee_name = person?.name ?? null;
    changes.assignee_type = "user";
  }
  if (body.clear_assignee === true) {
    changes.assignee_actor_id = null;
    changes.assignee_name = null;
    changes.assignee_type = null;
  }
  if (body.completed === true) changes.completed_at = NOW;
  if (body.completed === false) changes.completed_at = null;
  return changes;
}

/**
 * Everything the Ticket view reads and writes over one card in `state.card`: the card and its
 * wait routes (`ticketWorkHandlers`), the board, the Loop, its columns, the plan's readiness, the
 * labels, the people, the history, mentions and files, and the card's `PATCH`, move, archive and
 * confirm, each checking the version as the server does, and the card's notes (`noteHandlers`).
 * `state.bodies` holds every write's body, `state.csrf` the CSRF header of every write. `options`
 * give the Loop's fields (a completed stage), the notes and the card's history.
 */
export function ticketViewHandlers(
  initial: CardDetail = ticketCard(),
  options: { loop?: Partial<Loop>; notes?: CardNote[]; activity?: ActivityEntry[] } = {},
) {
  const work = ticketWorkHandlers(initial);
  const notes = noteHandlers(options.notes);
  const state = Object.assign(work.state, { csrf: [] as (string | null)[] });
  const change = (
    request: Request,
    route: string,
    apply: (body: Record<string, unknown>) => Partial<CardDetail> | Response,
  ) => changeCard(state, request, route, apply);

  const handlers = [
    // Answers nothing, so MSW moves on to the next handler: this one only records the header.
    http.all(apiPath("/*"), ({ request }) => {
      if (request.method !== "GET") state.csrf.push(request.headers.get("X-CSRF-Token"));
    }),
    ...work.handlers,
    ...notes.handlers,
    http.get(apiPath(`/boards/${BOARD_ID}`), () =>
      ok({ id: BOARD_ID, name: "Platform", status: "active", agent_ids: [], repository_ids: [] }),
    ),
    http.get(apiPath(LOOP_PATH), () => ok({ ...LOOP, stage: "in_progress", ...options.loop })),
    http.get(apiPath(`${LOOP_PATH}/lists`), () => ok(COLUMNS)),
    http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(READINESS)),
    http.get(apiPath(`/boards/${BOARD_ID}/labels`), () => ok(LABELS)),
    http.get(apiPath(`/boards/${BOARD_ID}/actors`), () => ok({ people: PEOPLE, agents: [] })),
    http.get(apiPath(`/boards/${BOARD_ID}/activity`), () => ok(options.activity ?? [])),
    http.get(apiPath(`/boards/${BOARD_ID}/attachments`), () => ok([])),
    http.get(apiPath(`${CARD_PATH}/mentions`), () => ok([])),
    http.get(apiPath("/agents/directory"), () => ok([])),
    http.patch(apiPath(CARD_PATH), ({ request }) => change(request, `PATCH ${CARD_PATH}`, patched)),
    http.post(apiPath(`${CARD_PATH}/comments`), async ({ request }) => {
      const body: unknown = await request.json();
      state.bodies.push({ route: `POST ${CARD_PATH}/comments`, body });
      const content = isRecord(body) && typeof body.content === "string" ? body.content : "";
      const created = {
        id: `comment-${state.bodies.length}`,
        card_id: CARD_ID,
        actor_id: MEMBER.id,
        actor_name: MEMBER.name,
        actor_type: "user",
        content,
        created_at: NOW,
        updated_at: NOW,
        after_loop_completed: false,
      };
      state.card = { ...state.card, comments: [...(state.card.comments ?? []), created] };
      return ok(created);
    }),
    http.post(apiPath(`${CARD_PATH}/move`), ({ request }) =>
      change(request, `POST ${CARD_PATH}/move`, (body) =>
        typeof body.list_id === "string"
          ? { list_id: body.list_id }
          : failure(422, "validation_error", "list_id is required"),
      ),
    ),
    http.post(apiPath(`${CARD_PATH}/confirm`), ({ request }) =>
      change(request, `POST ${CARD_PATH}/confirm`, () => ({
        completed_at: NOW,
        human_confirmed_at: NOW,
      })),
    ),
    http.post(apiPath(`${CARD_PATH}/archive`), ({ request }) => {
      state.bodies.push({ route: `POST ${requestPath(request)}`, body: null });
      return ok({ ...state.card, archived_at: NOW });
    }),
  ];
  return { state, notes: notes.state, handlers };
}
