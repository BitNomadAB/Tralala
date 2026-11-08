import { http } from "msw";
import type { Board, DiscussionInboxRow, Loop, LoopSummary } from "@/lib/types";
import { apiPath, ok, requestPath } from "./envelope";
import { LOOP, NOW } from "./loops";

/** A board as `GET /boards` lists it; `extra` replaces any field. */
export function board(id: string, name: string, extra: Partial<Board> = {}): Board {
  return {
    id,
    name,
    description: "",
    status: "active",
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
    schema_version: 21,
    schema_revision: null,
    loop_count: 0,
    list_count: 0,
    card_count: 0,
    repository_ids: [],
    agent_ids: [],
    repository_paths: {},
    ...extra,
  };
}

/** A Loop of a board's list; `extra` replaces any field. */
export function loop(id: string, name: string, extra: Partial<Loop> = {}): Loop {
  return { ...LOOP, id, name, key: `K-${id}`, ...extra };
}

/**
 * A Loop summary as `GET /boards/{id}/loop-summaries` gives it: by default a draft without Info,
 * waiting for a person. `extra.tickets` merges into the counts.
 */
export function summary(
  id: string,
  name: string,
  extra: Partial<Omit<LoopSummary, "tickets">> & { tickets?: Partial<LoopSummary["tickets"]> } = {},
): LoopSummary {
  const { tickets, ...rest } = extra;
  return {
    id,
    key: `K-${id}`,
    name,
    goal: "",
    stage: "draft",
    next: "Write the Loop's Info: what should change and why.",
    waiting_on: "person",
    execution_allowed: false,
    documents: {
      info: "empty",
      analysis_ai: "empty",
      analysis: "empty",
      roadmap_ai: "empty",
      roadmap: "empty",
    },
    ...rest,
    tickets: {
      ready: 0,
      needs_input: 0,
      blocked: 0,
      completed: 0,
      total: 0,
      needs_person: 0,
      by_column: {},
      ...tickets,
    },
  };
}

/**
 * The dashboard's network: `GET /boards` answers `boards` (any filter), each board's summaries
 * answer `summaries[board id]`, the discussion inbox answers `discussions`. `state.requests` is
 * every request, as "METHOD /path".
 */
export function dashboardHandlers(
  boards: Board[],
  summaries: Record<string, LoopSummary[]> = {},
  discussions: DiscussionInboxRow[] = [],
) {
  const state = { requests: [] as string[] };
  const handlers = [
    // Answers nothing, so MSW moves on to the next handler: this one only records the request.
    http.all(apiPath("/*"), ({ request }) => {
      state.requests.push(`${request.method} ${requestPath(request)}`);
    }),
    http.get(apiPath("/boards"), () =>
      ok(boards, { total: boards.length, limit: 50, offset: 0, has_more: false }),
    ),
    http.get(apiPath("/discussions/inbox"), () =>
      ok({ items: discussions, total: discussions.length }),
    ),
    http.get(apiPath("/boards/:boardId/loop-summaries"), ({ params }) => {
      const id = String(params.boardId);
      const loops = summaries[id] ?? [];
      return ok({ board_id: id, loops, count: loops.length });
    }),
  ];
  return { state, handlers };
}
