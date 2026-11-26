import { http } from "msw";
import type { Discussion } from "@/lib/types";
import { discussion } from "./discussions";
import { apiPath, failure, ok } from "./envelope";
import { BOARD_ID } from "./loops";

export const BOARD_TITLE = "Where the export lives";
export const BOARD_QUESTION = "Should the export live on the board or in each Loop?";

/** The fixture's thread, but on the board itself: no Ticket and no Loop, with its own title. */
export function boardThread(extra: Partial<Discussion> = {}): Discussion {
  return {
    ...discussion(),
    card_id: null,
    card_title: null,
    ticket_key: null,
    loop_id: null,
    loop_key: null,
    loop_name: null,
    title: BOARD_TITLE,
    goal: BOARD_QUESTION,
    ...extra,
  };
}

/** What the board's list and create were asked: each list's query, each create's body. */
export interface BoardDiscussionsState {
  threads: Discussion[];
  queries: URLSearchParams[];
  created: unknown[];
  /** What a create answers; null answers the board's 422 for a missing title. */
  answer: Discussion | null;
}

/**
 * `GET /boards/{id}/discussions` answering the threads that match `scope` and `state` (open is
 * every status but closed), and `POST` the same path answering `answer` with the body kept.
 */
export function boardDiscussionHandlers(threads: Discussion[], answer: Discussion | null = null) {
  const state: BoardDiscussionsState = { threads, queries: [], created: [], answer };
  const path = apiPath(`/boards/${BOARD_ID}/discussions`);
  const handlers = [
    http.get(path, ({ request }) => {
      const query = new URL(request.url).searchParams;
      state.queries.push(query);
      const scope = query.get("scope");
      const wanted = query.get("state");
      const items = state.threads.filter(
        (thread) =>
          (scope === null || (scope === "board") === (thread.card_id === null)) &&
          (wanted === null || (wanted === "closed") === (thread.status === "closed")),
      );
      return ok({ items, total: items.length });
    }),
    http.post(path, async ({ request }) => {
      const body: unknown = await request.json();
      state.created.push(body);
      if (state.answer === null) {
        return failure(422, "validation_failed", "Request validation failed", [
          { loc: ["body", "title"], msg: "A discussion on the board needs a title" },
        ]);
      }
      return ok(state.answer);
    }),
  ];
  return { state, handlers };
}
