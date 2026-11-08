import type {
  ActivityEntry,
  BoardList,
  Card,
  CardDetail,
  Checklist,
  ChecklistItem,
  Comment,
  MentionJob,
  PageMeta,
  Priority,
} from "../types";
import { json, request, type QueryValue } from "./client";

/** A Loop's lists and Tickets with their checklists, comments, mentions and activity. */
export const cardsApi = {
  async listLists(boardId: string, loopId: string): Promise<BoardList[]> {
    return json(await request<BoardList[]>(`/boards/${boardId}/loops/${loopId}/lists`));
  },

  async createList(boardId: string, loopId: string, name: string): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/loops/${loopId}/lists`, {
        method: "POST",
        body: { name },
      }),
    );
  },

  async renameList(
    boardId: string,
    loopId: string,
    listId: string,
    name: string,
  ): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/loops/${loopId}/lists/${listId}`, {
        method: "PATCH",
        body: { name },
      }),
    );
  },

  async moveList(
    boardId: string,
    loopId: string,
    listId: string,
    position: number,
  ): Promise<BoardList[]> {
    return json(
      await request<BoardList[]>(`/boards/${boardId}/loops/${loopId}/lists/${listId}/move`, {
        method: "POST",
        body: { position },
      }),
    );
  },

  async archiveList(boardId: string, loopId: string, listId: string): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/loops/${loopId}/lists/${listId}/archive`, {
        method: "POST",
      }),
    );
  },

  async listBoardTickets(
    boardId: string,
    params: { q?: string; limit?: number } = {},
  ): Promise<(Card & { loop_key: string; loop_name: string })[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    return json(
      await request<(Card & { loop_key: string; loop_name: string })[]>(
        `/boards/${boardId}/tickets?${query.toString()}`,
      ),
    );
  },

  async listCards(
    boardId: string,
    loopId: string,
    params: { list_id?: string | undefined; limit?: number; include_archived?: boolean } = {},
  ): Promise<Card[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    return json(
      await request<Card[]>(`/boards/${boardId}/loops/${loopId}/cards?${query.toString()}`),
    );
  },

  async searchCards(
    boardId: string,
    loopId: string,
    params: {
      q?: string | undefined;
      label?: string | undefined;
      priority?: Priority | undefined;
      overdue?: boolean | undefined;
      completed?: boolean;
      include_archived?: boolean;
      limit?: number;
    },
  ): Promise<{ items: Card[]; meta?: PageMeta | undefined }> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined && value !== "" && value !== false)
        .map(([key, value]) => [key, String(value)]),
    );
    const result = await request<Card[]>(
      `/boards/${boardId}/loops/${loopId}/search?${query.toString()}`,
    );
    return { items: result.data, meta: result.meta };
  },

  async getCard(boardId: string, loopId: string, cardId: string): Promise<CardDetail> {
    const result = await request<CardDetail>(
      `/boards/${boardId}/loops/${loopId}/cards/${cardId}?include=checklists,comments`,
    );
    return result.data;
  },

  async createCard(
    boardId: string,
    loopId: string,
    payload: {
      list_id: string;
      title: string;
      description?: string;
      priority?: Priority;
      due_at?: string | null;
      labels?: string[];
    },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async updateCard(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: {
      version: number;
      title?: string | undefined;
      description?: string | undefined;
      priority?: Priority | undefined;
      due_at?: string | undefined;
      clear_due_at?: boolean;
      completed?: boolean | undefined;
      labels?: string[];
      /** A person's actor id (or an enabled agent's) who owns the Ticket from now on. */
      assignee_actor_id?: string | undefined;
      clear_assignee?: boolean;
    },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async moveCard(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: { version: number; list_id: string; position: number },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/move`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async archiveCard(boardId: string, loopId: string, cardId: string): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/archive`, {
        method: "POST",
      }),
    );
  },

  async restoreCard(boardId: string, loopId: string, cardId: string): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/restore`, {
        method: "POST",
      }),
    );
  },

  async addChecklist(
    boardId: string,
    loopId: string,
    cardId: string,
    title: string,
  ): Promise<Checklist> {
    return json(
      await request<Checklist>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/checklists`, {
        method: "POST",
        body: { title },
      }),
    );
  },

  async addChecklistItem(
    boardId: string,
    checklistId: string,
    text: string,
  ): Promise<ChecklistItem> {
    return json(
      await request<ChecklistItem>(`/boards/${boardId}/checklists/${checklistId}/items`, {
        method: "POST",
        body: { text },
      }),
    );
  },

  async updateChecklistItem(
    boardId: string,
    itemId: string,
    payload: { text?: string; completed?: boolean },
  ): Promise<ChecklistItem> {
    return json(
      await request<ChecklistItem>(`/boards/${boardId}/checklist-items/${itemId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async deleteChecklistItem(boardId: string, itemId: string): Promise<void> {
    await request(`/boards/${boardId}/checklist-items/${itemId}`, { method: "DELETE" });
  },

  async addComment(
    boardId: string,
    loopId: string,
    cardId: string,
    content: string,
  ): Promise<Comment> {
    return json(
      await request<Comment>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/comments`, {
        method: "POST",
        body: { content },
      }),
    );
  },

  async listMentions(boardId: string, loopId: string, cardId: string): Promise<MentionJob[]> {
    return json(
      await request<MentionJob[]>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/mentions`),
    );
  },

  async retryMention(
    boardId: string,
    loopId: string,
    cardId: string,
    jobId: string,
  ): Promise<MentionJob> {
    return json(
      await request<MentionJob>(
        `/boards/${boardId}/loops/${loopId}/cards/${cardId}/mentions/${jobId}/retry`,
        { method: "POST" },
      ),
    );
  },

  async listActivity(
    boardId: string,
    params: { entity_id?: string | undefined; limit?: number } = {},
  ): Promise<ActivityEntry[]> {
    const query = new URLSearchParams(
      Object.entries<QueryValue>(params)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    );
    return json(await request<ActivityEntry[]>(`/boards/${boardId}/activity?${query.toString()}`));
  },
};
