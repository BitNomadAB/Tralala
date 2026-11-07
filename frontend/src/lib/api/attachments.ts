import type { Attachment } from "../types";
import { uploadContentType } from "./attachmentRules";
import { API_BASE, json, request } from "./client";

const attachmentsPath = (boardId: string): string => `/boards/${boardId}/attachments`;

/**
 * A Ticket's files. The upload is the file itself as the body, with its type as `Content-Type`
 * and its name and Ticket as query parameters; `request` sends a `Blob` body as it is and adds
 * the CSRF header to it as to every mutation.
 */
export const attachmentsApi = {
  async listAttachments(boardId: string, cardId: string): Promise<Attachment[]> {
    const query = new URLSearchParams({ card_id: cardId });
    return json(await request<Attachment[]>(`${attachmentsPath(boardId)}?${query.toString()}`));
  },

  async uploadAttachment(boardId: string, cardId: string, file: File): Promise<Attachment> {
    const query = new URLSearchParams({ card_id: cardId, filename: file.name });
    return json(
      await request<Attachment>(`${attachmentsPath(boardId)}?${query.toString()}`, {
        method: "POST",
        body: file,
        headers: { "Content-Type": uploadContentType(file) },
      }),
    );
  },

  /** The route that sends the bytes (`Content-Disposition: attachment`), for a link or an image. */
  attachmentDownloadUrl(boardId: string, attachmentId: string): string {
    return `${API_BASE}${attachmentsPath(boardId)}/${attachmentId}/download`;
  },

  async deleteAttachment(
    boardId: string,
    attachmentId: string,
  ): Promise<{ id: string; deleted: boolean }> {
    return json(
      await request<{ id: string; deleted: boolean }>(
        `${attachmentsPath(boardId)}/${attachmentId}`,
        { method: "DELETE" },
      ),
    );
  },
};
