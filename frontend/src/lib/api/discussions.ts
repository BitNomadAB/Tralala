import type {
  Discussion,
  DiscussionEvent,
  DiscussionInbox,
  DiscussionRun,
  DiscussionRunSummary,
} from "../types";
import { json, request } from "./client";

/** Ticket-bound discussions and their runs. */
export const discussionsApi = {
  /** Every board's threads that are not cancelled, grouped by who they wait for. */
  async discussionInbox(): Promise<DiscussionInbox> {
    return json(await request<DiscussionInbox>("/discussions/inbox"));
  },

  async listDiscussions(boardId: string): Promise<Discussion[]> {
    return json(await request<{ items: Discussion[] }>(`/boards/${boardId}/discussions`)).items;
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
    payload: { content: string; parent_message_id?: string },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}/messages`, {
        method: "POST",
        body: payload,
      }),
    );
  },
};
