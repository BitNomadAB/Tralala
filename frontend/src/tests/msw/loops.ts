import { http } from "msw";
import type { DocumentKind, GenerationRun, Loop, LoopDocument } from "@/lib/types";
import { apiPath, ok, requestPath } from "./envelope";

export const BOARD_ID = "board-1";
export const LOOP_ID = "loop-1";
export const NOW = "2026-11-03T10:00:00Z";
/** The Loop's own API path, e.g. `${LOOP_PATH}/documents`. */
export const LOOP_PATH = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
const KINDS: DocumentKind[] = ["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"];

export function emptyDocument(kind: DocumentKind): LoopDocument {
  return {
    loop_id: LOOP_ID,
    kind,
    state: "empty",
    current_revision_id: null,
    current_revision_number: null,
    current_content: null,
    current_payload: null,
    current_created_at: null,
    approved_revision_id: null,
    approved_revision_number: null,
    approved_content: null,
    stale: false,
    stale_reasons: [],
    revisions: [],
  };
}

export const DOCUMENTS = Object.fromEntries(
  KINDS.map((kind) => [kind, emptyDocument(kind)]),
) as Record<DocumentKind, LoopDocument>;

export const LOOP: Loop = {
  id: LOOP_ID,
  board_id: BOARD_ID,
  name: "Session expiry",
  goal: "",
  key: "SES-1",
  key_prefix: "SES",
  sequence: 1,
  stage: "draft",
  version: 1,
  created_at: NOW,
  updated_at: NOW,
  archived_at: null,
  cancelled_at: null,
  completed_at: null,
  history_id: null,
  documents: DOCUMENTS,
  plan: null,
  qa: null,
  progress: { ticket_total: 0, ticket_completed: 0, ticket_archived_incomplete: 0 },
  warnings: [],
};

/** An analysis run as the server serializes it; `extra` replaces any field. */
export function generationRun(
  status: GenerationRun["status"],
  phase: string | null,
  extra: Partial<GenerationRun> = {},
): GenerationRun {
  return {
    id: "run-1",
    loop_id: LOOP_ID,
    purpose: "analysis",
    status,
    phase,
    error_code: null,
    error_message: null,
    attempts: 1,
    output: {},
    source_revisions: {},
    created_at: NOW,
    started_at: status === "queued" ? null : NOW,
    finished_at: null,
    model: null,
    agent_name: null,
    usage: {},
    ...extra,
  };
}

/**
 * What the Plan tab's documents read when they open: the board, the agents, the Loop's documents and
 * agent choices, and the generation runs `state.runs` holds. `state.requests` is every request the
 * panel sent, as "METHOD /path".
 */
export function planningDialogHandlers(runs: GenerationRun[] = []) {
  const state = { runs, requests: [] as string[] };
  const handlers = [
    // Answers nothing, so MSW moves on to the next handler: this one only records the request.
    http.all(apiPath("/*"), ({ request }) => {
      state.requests.push(`${request.method} ${requestPath(request)}`);
    }),
    http.get(apiPath(`/boards/${BOARD_ID}`), () =>
      ok({
        id: BOARD_ID,
        name: "Platform",
        agent_ids: [],
        repository_ids: [],
        repository_paths: {},
      }),
    ),
    http.get(apiPath("/agents"), () => ok([])),
    http.get(apiPath(`${LOOP_PATH}/documents`), () =>
      ok({ loop_id: LOOP_ID, loop_version: 1, documents: DOCUMENTS, approvals: {} }),
    ),
    http.get(apiPath(`${LOOP_PATH}/agents`), () =>
      ok({
        loop_id: LOOP_ID,
        analysis_agent_id: null,
        roadmap_agent_id: null,
        qa_agent_id: null,
      }),
    ),
    http.get(apiPath(`${LOOP_PATH}/generation-runs`), () => ok(state.runs)),
  ];
  return { state, handlers };
}
