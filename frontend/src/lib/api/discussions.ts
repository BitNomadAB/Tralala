import type { Discussion, DiscussionBoard, DiscussionRun, DiscussionRunSummary } from "../types";
import { json, request } from "./client";

/** Ticket-bound discussions and their runs. */
export const discussionsApi = {
  async listDiscussionBoards(): Promise<DiscussionBoard[]> {
    return json(await request<{ items: DiscussionBoard[] }>("/discussions/overview")).items;
  },

  async listDiscussions(boardId: string): Promise<Discussion[]> {
    return json(await request<{ items: Discussion[] }>(`/boards/${boardId}/discussions`)).items;
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
