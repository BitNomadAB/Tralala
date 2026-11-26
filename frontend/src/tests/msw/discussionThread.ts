import { http } from "msw";
import type { Discussion, DiscussionEvent } from "@/lib/types";
import { apiPath, failure, ok } from "./envelope";
import { MEMBER } from "./session";

/** When the thread is closed in these tests. */
export const CLOSED_AT = "2026-11-08T12:00:00Z";

/**
 * What the discussion's API answers and has been sent: the thread, its stored events, every write
 * in `bodies`, in `next` the thread a write turns it into, by route ("messages", "start", "pause",
 * "resume", "stop", "close", "reopen"), and in `reads` how often the thread was marked read.
 */
export interface DiscussionApiState {
  discussion: Discussion;
  events: DiscussionEvent[];
  bodies: { route: string; body: unknown; csrf: string | null }[];
  next: Partial<Record<string, Discussion>>;
  reads: number;
}

/** The thread after a write to `route`: what the test set in `next`, or as it was. */
export function after(state: DiscussionApiState, route: string): Discussion {
  state.discussion = state.next[route] ?? state.discussion;
  return state.discussion;
}

/**
 * The thread's own actions at `path`, as the server answers them: read gives the reader's marker;
 * close is for the opener only (403 `not_opener`) and a thread already closed is a 409; reopen
 * opens a closed thread for anyone signed in, with the status `discussing`.
 */
export function threadHandlers(state: DiscussionApiState, path: string) {
  const record = (route: string, request: Request) => {
    state.bodies.push({ route, body: null, csrf: request.headers.get("X-CSRF-Token") });
  };
  return [
    http.post(apiPath(`${path}/read`), () => {
      state.reads += 1;
      return ok({
        discussion_id: state.discussion.id,
        actor_id: MEMBER.id,
        last_read_at: CLOSED_AT,
      });
    }),
    http.post(apiPath(`${path}/close`), ({ request }) => {
      record("close", request);
      if (!state.discussion.opened_by_me) {
        return failure(403, "not_opener", "Only the one who opened the discussion can close it");
      }
      if (state.discussion.status === "closed") {
        return failure(409, "conflict", "The discussion is already closed");
      }
      state.discussion = state.next.close ?? {
        ...state.discussion,
        status: "closed",
        closed_at: CLOSED_AT,
      };
      return ok(state.discussion);
    }),
    http.post(apiPath(`${path}/reopen`), ({ request }) => {
      record("reopen", request);
      if (state.discussion.status !== "closed") {
        return failure(409, "conflict", "The discussion is not closed");
      }
      state.discussion = state.next.reopen ?? {
        ...state.discussion,
        status: "discussing",
        closed_at: null,
      };
      return ok(state.discussion);
    }),
  ];
}
