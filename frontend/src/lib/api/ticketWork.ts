import type { Card, TicketFace, Wait, Workplace } from "../types";
import { json, request } from "./client";

const cardPath = (boardId: string, loopId: string, cardId: string): string =>
  `/boards/${boardId}/loops/${loopId}/cards/${cardId}`;

/**
 * A Ticket's face, where its work is done and what it waits for. Each change carries the card's
 * `version` and answers the updated card, so the next change can carry the new one.
 */
export const ticketWorkApi = {
  /**
   * A person's edit of the whole face (the summary included), which the server checks against its
   * template: `422 face_invalid` lists every message in `details.errors`; a token gets `403`.
   */
  async updateFace(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: TicketFace & { version: number },
  ): Promise<Card> {
    return json(
      await request<Card>(cardPath(boardId, loopId, cardId), { method: "PATCH", body: payload }),
    );
  },

  async setWorkplace(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: { version: number; workplace: Workplace },
  ): Promise<Card> {
    return json(
      await request<Card>(`${cardPath(boardId, loopId, cardId)}/workplace`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async setWait(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: { version: number; waiting_for: Wait; reason: string },
  ): Promise<Card> {
    return json(
      await request<Card>(`${cardPath(boardId, loopId, cardId)}/wait`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  /** A person's act: the server refuses it to a token. */
  async clearWait(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: { version: number },
  ): Promise<Card> {
    return json(
      await request<Card>(`${cardPath(boardId, loopId, cardId)}/wait/clear`, {
        method: "POST",
        body: payload,
      }),
    );
  },
};
