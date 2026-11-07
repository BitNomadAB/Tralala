import { http, HttpResponse } from "msw";
import type { Attachment } from "@/lib/types";
import { CARD_ID, PERSON_ID } from "./cards";
import { apiPath, failure, ok, REQUEST_ID } from "./envelope";
import { BOARD_ID, NOW } from "./loops";

/** The board's attachments route, e.g. `${ATTACHMENTS_PATH}/att-1/download`. */
export const ATTACHMENTS_PATH = `/boards/${BOARD_ID}/attachments`;

/** An attached file as the server serializes it (`AttachmentOut`). */
export function attachment(extra: Partial<Attachment> = {}): Attachment {
  return {
    id: "att-1",
    card_id: CARD_ID,
    discussion_id: null,
    message_id: null,
    original_filename: "notes.md",
    content_type: "text/markdown",
    size_bytes: 2560,
    sha256: "0".repeat(64),
    uploaded_by_actor_id: PERSON_ID,
    created_at: NOW,
    deleted_at: null,
    ...extra,
  };
}

/** One upload as the handler saw it: the query, the declared type, the body and the CSRF header. */
export interface SeenUpload {
  cardId: string | null;
  filename: string | null;
  contentType: string | null;
  csrf: string | null;
  body: string;
}

/**
 * The attachment routes over the rows in `state.rows`. An upload appends a row (the server derives
 * the stored type from the extension) unless `state.refuse` names a refusal to answer instead, the
 * way the server's 422/413/409 read. `state.uploads` and `state.deleted` record what was sent.
 */
export function attachmentHandlers(initial: Attachment[] = []) {
  const state = {
    rows: [...initial],
    uploads: [] as SeenUpload[],
    deleted: [] as string[],
    refuse: null as { status: number; code: string; message: string } | null,
    next: 1,
  };

  const handlers = [
    http.get(apiPath(ATTACHMENTS_PATH), ({ request }) => {
      const cardId = new URL(request.url).searchParams.get("card_id");
      return ok(state.rows.filter((row) => row.card_id === cardId));
    }),
    http.post(apiPath(ATTACHMENTS_PATH), async ({ request }) => {
      const query = new URL(request.url).searchParams;
      const seen: SeenUpload = {
        cardId: query.get("card_id"),
        filename: query.get("filename"),
        contentType: request.headers.get("Content-Type"),
        csrf: request.headers.get("X-CSRF-Token"),
        body: await request.text(),
      };
      state.uploads.push(seen);
      if (state.refuse) {
        const { status, code, message } = state.refuse;
        return failure(status, code, message);
      }
      const row = attachment({
        id: `att-new-${state.next}`,
        original_filename: seen.filename ?? "attachment",
        content_type: seen.contentType ?? "application/octet-stream",
        size_bytes: new TextEncoder().encode(seen.body).length,
      });
      state.next += 1;
      state.rows.push(row);
      // 201 as the route answers; the envelope is the one `ok` writes.
      return HttpResponse.json(
        { success: true, data: row, request_id: REQUEST_ID },
        { status: 201, headers: { "X-Request-ID": REQUEST_ID } },
      );
    }),
    http.delete(apiPath(`${ATTACHMENTS_PATH}/:attachmentId`), ({ params }) => {
      const id = String(params.attachmentId);
      if (state.refuse) {
        const { status, code, message } = state.refuse;
        return failure(status, code, message);
      }
      state.deleted.push(id);
      state.rows = state.rows.filter((row) => row.id !== id);
      return ok({ id, deleted: true });
    }),
  ];
  return { state, handlers };
}
