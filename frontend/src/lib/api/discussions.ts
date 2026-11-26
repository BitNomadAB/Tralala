import type {
  Discussion,
  DiscussionEvent,
  DiscussionFilters,
  DiscussionInbox,
  DiscussionReadMarker,
  DiscussionRun,
  DiscussionRunSummary,
} from "../types";
import { json, request, type QueryValue } from "./client";

/** A thread's own actions that take no body: close, reopen, mark read. */
function threadAction<T>(boardId: string, discussionId: string, action: string) {
  return request<T>(`/boards/${boardId}/discussions/${discussionId}/${action}`, {
    method: "POST",
  });
}

/** Discussions on a Ticket or on the board itself, and their runs. */
export const discussionsApi = {
  /** Every board's threads that are not cancelled, grouped by who they wait for. */
  async discussionInbox(): Promise<DiscussionInbox> {
    return json(await request<DiscussionInbox>("/discussions/inbox"));
  },

  /** A board's threads, newest activity first, narrowed by scope, open or closed, and the rest. */
  async listDiscussions(boardId: string, filters: DiscussionFilters = {}): Promise<Discussion[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>({ ...filters })
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    ).toString();
    const search = query === "" ? "" : `?${query}`;
    return json(await request<{ items: Discussion[] }>(`/boards/${boardId}/discussions${search}`))
      .items;
  },

  /** One Ticket's threads, newest activity first: the Ticket's Discussions tab. */
  async listTicketDiscussions(boardId: string, cardId: string): Promise<Discussion[]> {
    const query = new URLSearchParams({ card_id: cardId });
    return json(
      await request<{ items: Discussion[] }>(`/boards/${boardId}/discussions?${query.toString()}`),
    ).items;
  },

  async getDiscussion(boardId: string, discussionId: string): Promise<Discussion> {
    return json(await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}`));
  },

  async createDiscussion(
    boardId: string,
    payload: {
      card_id: string;
      title?: string;
      goal: string;
      mode?: string;
      participant_ids?: string[];
      max_rounds?: number;
    },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async startDiscussion(
    boardId: string,
    discussionId: string,
    payload: {
      rounds?: number | undefined;
      autonomous?: boolean;
      /** Run the round in the background so the view opens at once; a single round is inline otherwise. */
      background?: boolean;
      token_budget?: number | undefined;
      time_budget_seconds?: number | undefined;
    } = {},
  ): Promise<DiscussionRunSummary> {
    return json(
      await request(`/boards/${boardId}/discussions/${discussionId}/start`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async listDiscussionRuns(boardId: string, discussionId: string): Promise<DiscussionRun[]> {
    return json(
      await request<{ items: DiscussionRun[] }>(
        `/boards/${boardId}/discussions/${discussionId}/runs`,
      ),
    ).items;
  },

  async getDiscussionRun(
    boardId: string,
    discussionId: string,
    runId: string,
  ): Promise<DiscussionRun> {
    return json(
      await request<DiscussionRun>(`/boards/${boardId}/discussions/${discussionId}/runs/${runId}`),
    );
  },

  /** The thread's stored events after `after`, oldest first, at most `limit` (the server caps 500). */
  async listDiscussionEvents(
    boardId: string,
    discussionId: string,
    after = 0,
    limit = 500,
  ): Promise<DiscussionEvent[]> {
    const query = `after=${String(after)}&limit=${String(limit)}`;
    return json(
      await request<{ items: DiscussionEvent[] }>(
        `/boards/${boardId}/discussions/${discussionId}/events/history?${query}`,
      ),
    ).items;
  },

  async controlDiscussionRun(
    boardId: string,
    discussionId: string,
    runId: string,
    action: "pause" | "resume" | "stop",
  ): Promise<DiscussionRunSummary> {
    return json(
      await request(`/boards/${boardId}/discussions/${discussionId}/runs/${runId}/${action}`, {
        method: "POST",
        body: {},
      }),
    );
  },

  async reviewDiscussion(
    boardId: string,
    discussionId: string,
    payload: { decision: "approve" | "veto" | "rework"; reason?: string },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}/review`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async postDiscussionMessage(
    boardId: string,
    discussionId: string,
    /** `ticket`: a Ticket's key or id on the board the message points at. */
    payload: { content: string; parent_message_id?: string; ticket?: string },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}/messages`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  /** A discussion on the board itself: no Ticket, a title, and agents or nobody to answer. */
  async createBoardDiscussion(
    boardId: string,
    payload: {
      title: string;
      goal: string;
      mode?: string;
      participant_ids?: string[];
      max_rounds?: number;
    },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  /** Only the one who opened the thread closes it; it stays readable and takes comments. */
  async closeDiscussion(boardId: string, discussionId: string): Promise<Discussion> {
    return json(await threadAction<Discussion>(boardId, discussionId, "close"));
  },

  /** The opener or any signed-in person opens a closed thread again. */
  async reopenDiscussion(boardId: string, discussionId: string): Promise<Discussion> {
    return json(await threadAction<Discussion>(boardId, discussionId, "reopen"));
  },

  /** Everything in the thread is read by the signed-in reader, as of now. */
  async markDiscussionRead(boardId: string, discussionId: string): Promise<DiscussionReadMarker> {
    return json(await threadAction<DiscussionReadMarker>(boardId, discussionId, "read"));
  },
};
