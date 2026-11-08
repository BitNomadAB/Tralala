import { http } from "msw";
import type { CardNote } from "@/lib/types";
import { CARD_ID, CARD_PATH, isRecord } from "./cards";
import { apiPath, failure, ok, requestPath } from "./envelope";
import { NOW } from "./loops";
import { MEMBER } from "./session";

/** The Ticket's notes route, e.g. `${NOTES_PATH}/note-1`. */
export const NOTES_PATH = `${CARD_PATH}/notes`;

/** A note as the server serializes it (`CardNoteOut`), by the signed-in member unless told. */
export function cardNote(extra: Partial<CardNote> = {}): CardNote {
  return {
    id: "note-1",
    card_id: CARD_ID,
    author: MEMBER.name,
    author_actor_id: MEMBER.id,
    written_at: NOW,
    updated_at: NOW,
    text: "Try it on this Loop's analysis first.",
    version: 1,
    ...extra,
  };
}

/** The text of a note write, trimmed as the server does, or "" without one. */
function textOf(body: unknown): string {
  return isRecord(body) && typeof body.text === "string" ? body.text.trim() : "";
}

/**
 * The notes routes over the notes in `state.notes`, as the server answers them: oldest first, a
 * write by the signed-in member, `403 note_author_only` for someone else's note, `409
 * version_conflict` for a stale version, and `409 loop_read_only` for every write while
 * `state.readOnly` (a completed Loop). `state.writes` is every write as "METHOD /path" with its
 * body.
 */
export function noteHandlers(initial: CardNote[] = []) {
  const state = {
    notes: [...initial],
    readOnly: false,
    writes: [] as { route: string; body: unknown }[],
    next: 1,
  };
  const readOnlyRefusal = () =>
    state.readOnly ? failure(409, "loop_read_only", "This Loop is read-only") : null;
  const own = (id: string) => {
    const note = state.notes.find((row) => row.id === id);
    if (!note) return failure(404, "note_not_found", "Note not found");
    if (note.author_actor_id !== MEMBER.id) {
      return failure(403, "note_author_only", "Only the author can change a note");
    }
    return note;
  };

  const handlers = [
    http.get(apiPath(NOTES_PATH), () => ok(state.notes)),
    http.post(apiPath(NOTES_PATH), async ({ request }) => {
      const body: unknown = await request.json();
      state.writes.push({ route: `POST ${requestPath(request)}`, body });
      const refused = readOnlyRefusal();
      if (refused) return refused;
      const note = cardNote({ id: `note-new-${state.next}`, text: textOf(body) });
      state.next += 1;
      state.notes.push(note);
      return ok(note);
    }),
    http.patch(apiPath(`${NOTES_PATH}/:noteId`), async ({ request, params }) => {
      const body: unknown = await request.json();
      state.writes.push({ route: `PATCH ${requestPath(request)}`, body });
      const refused = readOnlyRefusal();
      if (refused) return refused;
      const note = own(String(params.noteId));
      if (note instanceof Response) return note;
      if (!isRecord(body) || body.version !== note.version) {
        return failure(409, "version_conflict", "The note changed since it was read");
      }
      const edited = { ...note, text: textOf(body), version: note.version + 1, updated_at: NOW };
      state.notes = state.notes.map((row) => (row.id === note.id ? edited : row));
      return ok(edited);
    }),
    http.delete(apiPath(`${NOTES_PATH}/:noteId`), ({ request, params }) => {
      state.writes.push({ route: `DELETE ${requestPath(request)}`, body: null });
      const refused = readOnlyRefusal();
      if (refused) return refused;
      const note = own(String(params.noteId));
      if (note instanceof Response) return note;
      state.notes = state.notes.filter((row) => row.id !== note.id);
      return ok({ id: note.id, deleted: true });
    }),
  ];
  return { state, handlers };
}
