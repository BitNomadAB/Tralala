import type { LoopDocument, TicketFace, WaitingFor, Workplace } from "@/lib/types";
import { formatDate } from "@/lib/utils";

/*
 * Reading a RoadMap for its review: the plan's Phases and Tickets as a person judges them, from the
 * technical revision's payload (the canonical plan) or a kept candidate. Pure, so each rule is
 * tested on its own; the server validated the shape, and anything missing reads as empty.
 */

/** A planned Ticket as its review row shows it. `face` is null for one written before faces. */
export interface ReviewTicket {
  id: string;
  key: string;
  title: string;
  summary: string;
  objective: string;
  needsPerson: boolean;
  workplace: Workplace;
  waitingFor: WaitingFor;
  waitingReason: string;
  acceptanceCriteria: string[];
  face: TicketFace | null;
}

export interface ReviewPhase {
  id: string;
  number: number;
  name: string;
  objective: string;
  tickets: ReviewTicket[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function texts(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

const WORKPLACES: readonly Workplace[] = ["codebase", "outside", "unknown"];
const WAITS: readonly WaitingFor[] = [
  "nothing",
  "decision",
  "information",
  "access",
  "third_party",
];

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.find((entry) => entry === value) ?? fallback;
}

/** The face a planned Ticket carries, or null when it has none of the five sections. */
export function planFace(ticket: Record<string, unknown>): TicketFace | null {
  const face: TicketFace = {
    summary: text(ticket.summary),
    why: text(ticket.why),
    if_skipped: text(ticket.if_skipped),
    pros: texts(ticket.pros),
    cons: texts(ticket.cons),
    steps: texts(ticket.steps),
  };
  const empty =
    !face.why &&
    !face.if_skipped &&
    face.pros.length === 0 &&
    face.cons.length === 0 &&
    face.steps.length === 0;
  return empty ? null : face;
}

function reviewTicket(ticket: Record<string, unknown>): ReviewTicket {
  return {
    id: text(ticket.id),
    key: text(ticket.key),
    title: text(ticket.title),
    summary: text(ticket.summary),
    objective: text(ticket.objective),
    needsPerson: ticket.required_actor === "human",
    workplace: oneOf(ticket.workplace, WORKPLACES, "unknown"),
    waitingFor: oneOf(ticket.waiting_for, WAITS, "nothing"),
    waitingReason: text(ticket.waiting_reason),
    acceptanceCriteria: texts(ticket.acceptance_criteria),
    face: planFace(ticket),
  };
}

/** The plan's Phases in their order, each with its Tickets; null when the payload has none. */
export function reviewPlan(payload: unknown): ReviewPhase[] | null {
  if (!isRecord(payload)) return null;
  const phases = records(payload.phases).map((phase) => ({
    id: text(phase.id),
    number: typeof phase.number === "number" ? phase.number : 0,
    name: text(phase.name),
    objective: text(phase.objective),
    tickets: records(phase.tickets).map(reviewTicket),
  }));
  if (phases.length === 0) return null;
  return [...phases].sort((left, right) => left.number - right.number);
}

/** The plan's own summary sentence, the "In short" of a RoadMap nobody wrote a brief for. */
export function planSummary(payload: unknown): string {
  return isRecord(payload) ? text(payload.summary) : "";
}

export function ticketCount(phases: readonly ReviewPhase[] | null): number {
  return (phases ?? []).reduce((total, phase) => total + phase.tickets.length, 0);
}

export function ticketsText(count: number): string {
  return count === 1 ? "1 Ticket" : `${count} Tickets`;
}

/** "Approve RoadMap · 3 Tickets": the decision with what it publishes. */
export function approveRoadmapLabel(count: number): string {
  return count > 0 ? `Approve RoadMap · ${ticketsText(count)}` : "Approve RoadMap";
}

/** What approving binds to and does: "Revision 2 of 7 Nov 2026. Approving publishes …". */
export function approvalLine(document: LoopDocument | undefined, count: number): string | null {
  const number = document?.current_revision_number;
  if (!number) return null;
  const revision = document.current_created_at
    ? `Revision ${number} of ${formatDate(document.current_created_at)}.`
    : `Revision ${number}.`;
  const publishes =
    count > 0
      ? ` Approving publishes its ${ticketsText(count)} to the Kanban.`
      : " Approving publishes its Tickets to the Kanban.";
  return revision + publishes;
}

/** Where the work is done, as one small word in the row. */
export const WORKPLACE_WORDS: Record<Workplace, string> = {
  codebase: "In the code base",
  outside: "Outside",
  unknown: "Unknown",
};

const WAIT_WORDS: Record<Exclude<WaitingFor, "nothing">, string> = {
  decision: "a decision",
  information: "information",
  access: "access",
  third_party: "a third party",
};

/** "Waits for a decision: who signs the policy" for a Ticket planned with a wait, else null. */
export function waitLine(
  ticket: Pick<ReviewTicket, "waitingFor" | "waitingReason">,
): string | null {
  if (ticket.waitingFor === "nothing") return null;
  const what = `Waits for ${WAIT_WORDS[ticket.waitingFor]}`;
  return ticket.waitingReason ? `${what}: ${ticket.waitingReason}` : what;
}

/** The muted line under the title: the face's summary, or the objective of a Ticket without one. */
export function rowLine(ticket: ReviewTicket): string {
  return ticket.face ? ticket.summary || ticket.objective : ticket.objective || ticket.summary;
}

/** The payload as Raw text shows it: indented JSON. */
export function payloadText(payload: unknown): string {
  return JSON.stringify(payload, null, 2);
}
