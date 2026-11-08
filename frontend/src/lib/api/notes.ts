import type { CardNote } from "../types";
import { json, request } from "./client";

const notesPath = (boardId: string, loopId: string, cardId: string): string =>
  `/boards/${boardId}/loops/${loopId}/cards/${cardId}/notes`;

/**
 * A person's notes on a Ticket. Every write is a person's (a token is refused with
 * `403 human_action_required`); only the author edits or deletes a note (`note_author_only`), an
 * edit carries the version it read (`409 version_conflict`), and a completed, cancelled or archived
 * Loop refuses every write (`409 loop_read_only`).
 */
export const notesApi = {
  async listCardNotes(boardId: string, loopId: string, cardId: string): Promise<CardNote[]> {
    return json(await request<CardNote[]>(notesPath(boardId, loopId, cardId)));
  },

  async addCardNote(
    boardId: string,
    loopId: string,
    cardId: string,
    text: string,
  ): Promise<CardNote> {
    return json(
      await request<CardNote>(notesPath(boardId, loopId, cardId), {
        method: "POST",
        body: { text },
      }),
    );
  },

  async editCardNote(
    boardId: string,
    loopId: string,
    cardId: string,
    noteId: string,
    payload: { text: string; version: number },
  ): Promise<CardNote> {
    return json(
      await request<CardNote>(`${notesPath(boardId, loopId, cardId)}/${noteId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async deleteCardNote(
    boardId: string,
    loopId: string,
    cardId: string,
    noteId: string,
  ): Promise<void> {
    await request(`${notesPath(boardId, loopId, cardId)}/${noteId}`, { method: "DELETE" });
  },
};
