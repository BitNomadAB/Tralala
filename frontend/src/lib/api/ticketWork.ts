import type { Card, Wait, Workplace } from "../types";
import { json, request } from "./client";

const cardPath = (boardId: string, loopId: string, cardId: string): string =>
  `/boards/${boardId}/loops/${loopId}/cards/${cardId}`;

/**
 * Where a Ticket's work is done and what it waits for. Each change carries the card's `version`
 * and answers the updated card, so the next change can carry the new one.
 */
export const ticketWorkApi = {
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
