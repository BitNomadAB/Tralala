import type { Loop } from "../types";
import { json, request, type QueryValue } from "./client";

/** Loops and their lifecycle. */
export const loopsApi = {
  async listLoops(
    boardId: string,
    params: { include_completed?: boolean; include_archived?: boolean } = {},
  ): Promise<Loop[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    );
    return json(await request<Loop[]>(`/boards/${boardId}/loops?${query.toString()}`));
  },

  async createLoop(
    boardId: string,
    payload: { name: string; goal?: string; column_names?: string[] },
  ): Promise<Loop> {
    return json(await request<Loop>(`/boards/${boardId}/loops`, { method: "POST", body: payload }));
  },

  async getLoop(boardId: string, loopId: string): Promise<Loop> {
    return json(await request<Loop>(`/boards/${boardId}/loops/${loopId}`));
  },

  async updateLoop(
    boardId: string,
    loopId: string,
    payload: { version: number; name?: string; goal?: string },
  ): Promise<Loop> {
    return json(
      await request<Loop>(`/boards/${boardId}/loops/${loopId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async cancelLoop(boardId: string, loopId: string, payload: { version: number; reason?: string }) {
    return json(
      await request<Loop>(`/boards/${boardId}/loops/${loopId}/cancel`, {
        method: "POST",
        body: payload,
      }),
    );
  },
};
