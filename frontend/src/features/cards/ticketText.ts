import type {
  ActivityEntry,
  Comment,
  LoopReadiness,
  PlanTicketView,
  TicketFace,
} from "@/lib/types";
import { FACE_MAX_STEPS } from "./faceLimits";

/*
 * The words of the Ticket's main column that are worked out from its data: the foot line under the
 * steps, the hints on the expanders, the plan entry of Raw text, the history's sentences and the
 * completions of Work. Pure, so each is tested on its own.
 */

/** What the foot line under the steps says: how many of five, or why there are no more. */
export function stepsFoot(count: number): string {
  return count >= FACE_MAX_STEPS
    ? "Five of five. A Ticket that needs more steps is split into another Ticket when the RoadMap is written."
    : `${count} of ${FACE_MAX_STEPS}`;
}

/** The hint on Pro and con: "3 for, 2 against". */
export function prosConsHint(face: Pick<TicketFace, "pros" | "cons">): string {
  return `${face.pros.length} for, ${face.cons.length} against`;
}

/** The hint on Your notes: "1 note", "3 notes". */
export function notesHint(count: number): string {
  return count === 1 ? "1 note" : `${count} notes`;
}

/**
 * The plan item's own fields as the Plan entry shows them: what the planner wrote, without what
 * the server computes on every read (ready, blockers, state, completion), without the lists shown
 * above it, and with the Tickets it depends on by key. Empty texts and lists are left out.
 */
export function planEntryText(item: PlanTicketView, readiness: LoopReadiness | undefined): string {
  const keyOf = new Map((readiness?.items ?? []).map((entry) => [entry.id, entry.key]));
  const entry: Record<string, unknown> = {
    id: item.key,
    title: item.title,
    phase: item.phase_number,
    objective: item.objective,
    instructions: item.instructions,
    required_actor: item.required_actor,
    execution_mode: item.execution_mode,
    human_action_reason: item.human_action_reason,
    human_instructions: item.human_instructions,
    depends_on: item.prerequisite_ticket_ids.map((id) => keyOf.get(id) ?? id),
    workplace: item.workplace,
  };
  const kept = Object.entries(entry).filter(
    ([, value]) => value !== "" && !(Array.isArray(value) && value.length === 0),
  );
  return JSON.stringify(Object.fromEntries(kept), null, 2);
}

/** The line a completion comment carries before its evidence (`completion_comment`). */
const EVIDENCE_MARK = "\n\n**Evidence**\n\n";

/** The comments that record a completion with its evidence, oldest first. */
export function completionComments(comments: readonly Comment[]): Comment[] {
  return comments.filter((comment) => comment.content.includes(EVIDENCE_MARK));
}

/** What each recorded action did, after the name of whoever did it. */
const ACTIONS: Readonly<Record<string, string>> = {
  "card.create": "created this Ticket",
  "card.created": "created this Ticket",
  "card.bulk_create": "created this Ticket",
  "card.moved": "moved this Ticket to another column",
  "card.archived": "archived this Ticket",
  "card.restored": "restored this Ticket",
  "card.human_confirmed": "confirmed the human action",
  "card.wait_set": "marked this Ticket as waiting",
  "card.wait_cleared": "cleared the wait",
  "card.workplace_changed": "changed where the work is done",
  "card.note_added": "added a note",
  "card.note_edited": "edited a note",
  "card.note_deleted": "deleted a note",
  "comment.created": "commented",
  "comment.updated": "edited a comment",
  "comment.deleted": "deleted a comment",
  "comment.agent_mentioned": "brought in an agent",
  "comment.agent_replied": "answered a mention",
  "comment.agent_failed": "could not answer a mention",
  "comment.mention_retried": "retried a mention",
  "attachment.uploaded": "attached a file",
  "attachment.deleted": "deleted a file",
  "checklist.created": "added a checklist",
  "checklist.updated": "changed a checklist",
  "checklist.deleted": "deleted a checklist",
  "checklist.item_added": "added a checklist item",
  "checklist.item_updated": "changed a checklist item",
  "checklist.item_deleted": "deleted a checklist item",
};

/** The fields a `card.updated` entry names, as a person reads them. */
const FIELDS: Readonly<Record<string, string>> = {
  title: "the title",
  description: "the description",
  priority: "the priority",
  due_at: "the due date",
  labels: "the labels",
  assignee: "the owner",
  summary: "the summary",
  face: "the face",
};

const WHO: Readonly<Record<ActivityEntry["actor_type"], string>> = {
  user: "A person",
  agent: "An agent",
  service: "Tralala",
};

function updated(changes: Record<string, unknown>): string {
  const completed = changes.completed;
  if (completed !== undefined) {
    const reopened =
      typeof completed === "object" &&
      completed !== null &&
      "after" in completed &&
      completed.after === false;
    return reopened ? "reopened this Ticket" : "completed this Ticket";
  }
  const named = Object.keys(changes).map((key) => FIELDS[key] ?? key.replaceAll("_", " "));
  if (named.length === 0) return "changed this Ticket";
  const last = named.pop() ?? "";
  return `changed ${named.length > 0 ? `${named.join(", ")} and ${last}` : last}`;
}

/** One entry as a sentence: who, then what they did ("Ada Member changed the title"). */
export function historyLine(entry: ActivityEntry, name: string | null): string {
  const who = name ?? WHO[entry.actor_type];
  const what =
    entry.action === "card.updated"
      ? updated(entry.changes)
      : (ACTIONS[entry.action] ?? entry.action);
  return `${who} ${what}`;
}

/** Whoever did something, when the board does not know their name. */
export function whoText(type: ActivityEntry["actor_type"]): string {
  return WHO[type];
}
