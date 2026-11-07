/**
 * A file attached to a Ticket, as `GET /boards/{board_id}/attachments` answers it. The bytes are
 * served by the download route; the entry names who uploaded it by actor id only.
 */
export interface Attachment {
  id: string;
  card_id: string | null;
  discussion_id?: string | null;
  message_id?: string | null;
  /** Sanitized by the server: no separators, no leading dots. Display only. */
  original_filename: string;
  /** The type the server derived from the extension, not the one the upload declared. */
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by_actor_id: string;
  created_at: string;
  deleted_at?: string | null;
}
