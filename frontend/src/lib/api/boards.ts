import type {
  Board,
  HistoryDetail,
  HistorySummary,
  Label,
  Repository,
  RepositoryCheck,
  PageMeta,
} from "../types";
import { json, request, type QueryValue } from "./client";

/** Boards and what belongs to the board itself: labels, export, history, repositories. */
export const boardsApi = {
  async listBoards(
    params: {
      q?: string | undefined;
      status?: string | undefined;
      sort?: string;
      order?: string;
      limit?: number;
    } = {},
  ) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, value]) => Boolean(value)) as [string, string][],
    );
    const result = await request<Board[]>(`/boards?${query.toString()}`);
    return { items: result.data, meta: result.meta };
  },

  async getBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}`));
  },

  async createBoard(payload: {
    name: string;
    description?: string;
    template_id?: string | null;
    repository_ids?: string[];
    agent_ids?: string[];
  }): Promise<Board> {
    return json(await request<Board>("/boards", { method: "POST", body: payload }));
  },

  async updateBoard(
    boardId: string,
    payload: {
      name?: string;
      description?: string;
      repository_ids?: string[];
      agent_ids?: string[];
    },
  ): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}`, { method: "PATCH", body: payload }));
  },

  async archiveBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/archive`, { method: "POST" }));
  },

  async restoreBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/restore`, { method: "POST" }));
  },

  async duplicateBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/duplicate`, { method: "POST" }));
  },

  async deleteBoard(boardId: string, confirmName: string): Promise<void> {
    await request(`/boards/${boardId}`, { method: "DELETE", body: { confirm_name: confirmName } });
  },

  exportUrl(boardId: string): string {
    return `/api/v1/boards/${boardId}/export`;
  },

  async importBoard(file: File): Promise<Board> {
    return json(
      await request<Board>("/boards/import", {
        method: "POST",
        body: file,
        headers: { "Content-Type": "application/zip" },
      }),
    );
  },

  async retryMigration(boardId: string): Promise<{ status: string; to_revision: string | null }> {
    return json(await request(`/boards/${boardId}/migrate`, { method: "POST" }));
  },

  async listLabels(boardId: string): Promise<Label[]> {
    return json(await request<Label[]>(`/boards/${boardId}/labels`));
  },

  async createLabel(boardId: string, name: string, color: string): Promise<Label> {
    return json(
      await request<Label>(`/boards/${boardId}/labels`, {
        method: "POST",
        body: { name, color },
      }),
    );
  },

  async searchHistory(
    boardId: string,
    params: {
      q?: string | undefined;
      source_kind?: string | undefined;
      qa_status?: string | undefined;
      limit?: number;
      offset?: number;
    },
  ): Promise<{ items: HistorySummary[]; meta?: PageMeta | undefined }> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    const result = await request<HistorySummary[]>(
      `/boards/${boardId}/history?${query.toString()}`,
    );
    return { items: result.data, meta: result.meta };
  },

  async getHistoryRecord(boardId: string, historyId: string): Promise<HistoryDetail> {
    return json(await request<HistoryDetail>(`/boards/${boardId}/history/${historyId}`));
  },

  async importLegacyRecord(
    boardId: string,
    payload: Record<string, unknown>,
  ): Promise<HistoryDetail> {
    return json(
      await request<HistoryDetail>(`/boards/${boardId}/history/import`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async listRepositories(params: { board_id?: string } = {}): Promise<Repository[]> {
    const query = params.board_id ? `?board_id=${encodeURIComponent(params.board_id)}` : "";
    return json(await request<Repository[]>(`/repositories${query}`));
  },

  async createRepository(payload: {
    name?: string | undefined;
    url: string;
    branch?: string | null;
    enabled?: boolean;
    token?: string;
  }): Promise<Repository> {
    return json(await request<Repository>("/repositories", { method: "POST", body: payload }));
  },

  async updateRepository(
    repositoryId: string,
    payload: {
      name?: string | undefined;
      url?: string;
      branch?: string | null;
      enabled?: boolean;
      token?: string;
      clear_token?: boolean;
    },
  ): Promise<Repository> {
    return json(
      await request<Repository>(`/repositories/${repositoryId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async deleteRepository(repositoryId: string): Promise<void> {
    await request(`/repositories/${repositoryId}`, { method: "DELETE" });
  },

  async checkRepository(repositoryId: string): Promise<RepositoryCheck> {
    return json(
      await request<RepositoryCheck>(`/repositories/${repositoryId}/check`, {
        method: "POST",
      }),
    );
  },
};
