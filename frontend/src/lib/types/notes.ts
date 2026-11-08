/** A person's note on a Ticket: written by a person, never by an agent; a coding agent reads it. */
export interface CardNote {
  id: string;
  card_id: string;
  /** The author's name when the note was written. */
  author: string;
  /** Whether the person reading wrote it: only the author edits or deletes a note. */
  author_actor_id: string;
  written_at: string;
  updated_at: string;
  text: string;
  version: number;
}
