import { ApiError } from "@/lib/api";
import type { TicketFace } from "@/lib/types";

/**
 * The face's limits and counting rules as the server has them (`backend/app/services/
 * ticket_face.py`), for the counters a person sees while editing. The server stays the judge: it
 * also checks the plain-text rules (no code, file path or id), and its messages are shown as it
 * words them.
 */
export const FACE_MAX_SUMMARY_WORDS = 20;
export const FACE_MAX_SENTENCES = 3;
export const FACE_MAX_POINTS = 3;
export const FACE_MIN_STEPS = 1;
export const FACE_MAX_STEPS = 5;

/** The face's fields, in the order a writer writes them; the summary is its own column. */
export const FACE_FIELDS = ["summary", "why", "if_skipped", "pros", "cons", "steps"] as const;

export type FaceField = (typeof FACE_FIELDS)[number];

/** The whitespace-separated tokens of `text` (Python's `str.split()`). */
export function wordCount(text: string): number {
  return text.split(/\s+/).filter((token) => token !== "").length;
}

/**
 * The sentences of `text`: each run of `.`, `!` or `?` followed by whitespace or the end ends one,
 * and text after the last end is one more. An abbreviation ends a sentence too ("e.g. this" is
 * two); "3.5" ends none. An empty text has none.
 */
export function sentenceCount(text: string): number {
  const stripped = text.trim();
  if (stripped === "") return 0;
  const ends = Array.from(stripped.matchAll(/[.!?]+(?=\s|$)/g));
  const last = ends.at(-1);
  const tail = last === undefined ? stripped : stripped.slice(last.index + last[0].length);
  return ends.length + (tail.trim() === "" ? 0 : 1);
}

/** A list field typed one item per line: the lines with text, trimmed. */
export function listItems(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** One counter under a field: what it says and whether the text is over the limit. */
export interface FaceCount {
  text: string;
  over: boolean;
}

function count(value: number, most: number, unit: string, least = 0): FaceCount {
  return { text: `${value} of ${most} ${unit}`, over: value > most || value < least };
}

/** The draft as a person types it: the texts as they are, each list one item per line. */
export interface FaceDraft {
  summary: string;
  why: string;
  if_skipped: string;
  pros: string;
  cons: string;
  steps: string;
}

/** The counter of every field: "14 of 20 words", "2 of 3 sentences", "4 of 5 steps". */
export function faceCounts(draft: FaceDraft): Record<FaceField, FaceCount> {
  return {
    summary: count(wordCount(draft.summary), FACE_MAX_SUMMARY_WORDS, "words", 1),
    why: count(sentenceCount(draft.why), FACE_MAX_SENTENCES, "sentences", 1),
    if_skipped: count(sentenceCount(draft.if_skipped), FACE_MAX_SENTENCES, "sentences", 1),
    pros: count(listItems(draft.pros).length, FACE_MAX_POINTS, "points"),
    cons: count(listItems(draft.cons).length, FACE_MAX_POINTS, "points"),
    steps: count(listItems(draft.steps).length, FACE_MAX_STEPS, "steps", FACE_MIN_STEPS),
  };
}

/** The draft a face starts from; without a face, the summary alone (it may already exist). */
export function draftOf(face: TicketFace | null, summary: string): FaceDraft {
  return {
    summary: face?.summary ?? summary,
    why: face?.why ?? "",
    if_skipped: face?.if_skipped ?? "",
    pros: (face?.pros ?? []).join("\n"),
    cons: (face?.cons ?? []).join("\n"),
    steps: (face?.steps ?? []).join("\n"),
  };
}

/** The face a draft sends: the texts trimmed, the lists one item per line with text. */
export function faceOf(draft: FaceDraft): TicketFace {
  return {
    summary: draft.summary.trim(),
    why: draft.why.trim(),
    if_skipped: draft.if_skipped.trim(),
    pros: listItems(draft.pros),
    cons: listItems(draft.cons),
    steps: listItems(draft.steps),
  };
}

/** The server's messages, each under the field it names, and the ones that name none. */
export interface FaceErrors {
  fields: Partial<Record<FaceField, string[]>>;
  other: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The field a path names ("steps[2]" is steps), or null for anything else. */
function fieldOf(path: unknown): FaceField | null {
  if (typeof path !== "string") return null;
  const base = path.replace(/\[\d+\]$/, "");
  return FACE_FIELDS.find((field) => field === base) ?? null;
}

/** The field a message names after its Ticket ("Ticket X, steps[2]: …"), or null. */
function fieldInMessage(message: string): FaceField | null {
  const match = /, (summary|why|if_skipped|pros|cons|steps)(?:\[\d+\])?: /.exec(message);
  return fieldOf(match?.[1]);
}

/**
 * A `422 face_invalid` as messages under their fields: `details.errors` holds the messages and
 * `details.faces` the field of each, in the same order; a message whose field is not given is
 * matched by the field it names. Null for any other error.
 */
export function faceErrors(error: unknown): FaceErrors | null {
  if (!(error instanceof ApiError) || error.code !== "face_invalid") return null;
  const details = isRecord(error.details) ? error.details : {};
  const messages = Array.isArray(details.errors)
    ? details.errors.filter((entry): entry is string => typeof entry === "string")
    : [];
  const faces = Array.isArray(details.faces) ? details.faces : [];
  const result: FaceErrors = { fields: {}, other: [] };
  messages.forEach((message, index) => {
    const entry: unknown = faces[index];
    const field = (isRecord(entry) ? fieldOf(entry.field) : null) ?? fieldInMessage(message);
    if (field === null) {
      result.other.push(message);
      return;
    }
    result.fields[field] = [...(result.fields[field] ?? []), message];
  });
  if (messages.length === 0) result.other.push(error.message);
  return result;
}
