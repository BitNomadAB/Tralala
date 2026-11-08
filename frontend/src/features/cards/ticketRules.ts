import type { BoardList, Card, LoopReadiness, Priority } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { WAIT_LABELS, WAITS } from "./ticketWork";

/** The Ticket's own page, where "Open as page" goes and what "Copy link" copies. */
export function ticketPagePath(boardId: string, loopId: string, cardId: string): string {
  return `/boards/${encodeURIComponent(boardId)}/loops/${encodeURIComponent(loopId)}/tickets/${encodeURIComponent(cardId)}`;
}

/** The Loop page with its Kanban, where "Back to the board" goes. */
export function loopPagePath(boardId: string, loopId: string): string {
  return `/boards/${encodeURIComponent(boardId)}/loops/${encodeURIComponent(loopId)}`;
}

/** The Loop's columns as the Kanban shows them: in their order, without the archived ones. */
export function columnsInOrder(lists: readonly BoardList[]): BoardList[] {
  return lists
    .filter((list) => list.archived_at === null)
    .slice()
    .sort((a, b) => a.position - b.position);
}

/**
 * Where "Start work" moves the Ticket: the column after the first, while the Ticket sits in the
 * first column and is not completed. Null otherwise, and then "Mark complete" is the decision.
 */
export function startWorkTarget(card: Card, lists: readonly BoardList[]): BoardList | null {
  if (card.completed_at !== null) return null;
  const columns = columnsInOrder(lists);
  if (columns[0]?.id !== card.list_id) return null;
  return columns[1] ?? null;
}

/** The name of the Ticket's Phase from the plan, or null while the plan is not loaded. */
export function phaseName(card: Card, readiness: LoopReadiness | undefined): string | null {
  if (card.phase_number === null) return null;
  return readiness?.phases.find((phase) => phase.number === card.phase_number)?.name ?? null;
}

/** "Phase 7 · Decisions in the Loop", or "Phase 7" while the plan is not loaded. */
export function phaseText(card: Card, readiness: LoopReadiness | undefined): string | null {
  if (card.phase_number === null) return null;
  const name = phaseName(card, readiness);
  return name
    ? `Phase ${String(card.phase_number)} · ${name}`
    : `Phase ${String(card.phase_number)}`;
}

export interface Dependency {
  id: string;
  key: string;
  done: boolean;
}

/** The Tickets this one waits for, from the plan; empty while the plan is not loaded. */
export function dependencies(card: Card, readiness: LoopReadiness | undefined): Dependency[] {
  if (!readiness || card.plan_item_id === null) return [];
  const items = new Map(readiness.items.map((item) => [item.id, item]));
  const own = items.get(card.plan_item_id);
  if (!own) return [];
  return own.prerequisite_ticket_ids.flatMap((id) => {
    const item = items.get(id);
    return item ? [{ id: item.id, key: item.key, done: item.completed_at !== null }] : [];
  });
}

/** What follows the state word: "nothing holds it up", or what it waits for and why. */
export function stateReason(card: Card): string {
  const kind = WAITS.find((wait) => wait === card.waiting_for);
  if (kind) {
    const what = `waits for ${WAIT_LABELS[kind].toLowerCase()}`;
    return card.waiting_reason ? `${what}: ${card.waiting_reason}` : what;
  }
  if (!card.ready && card.blockers.length > 0) {
    const names = card.blockers.map((blocker) =>
      blocker.type === "phase"
        ? `Phase ${String(blocker.phase_number ?? "?")}`
        : (blocker.key ?? blocker.title ?? "earlier work"),
    );
    return `waits for ${names.join(", ")}`;
  }
  return "nothing holds it up";
}

/** When the Ticket was created and where it came from: "7 Nov 2026, from the RoadMap". */
export function createdText(card: Card): string {
  const date = formatDate(card.created_at);
  return card.plan_item_id === null ? date : `${date}, from the RoadMap`;
}

const PRIORITY_LABELS: Record<Priority, string> = {
  none: "None",
  low: "Low",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

/** A priority as the rail shows it. */
export function priorityLabel(priority: Priority): string {
  return PRIORITY_LABELS[priority];
}

/** Why "Mark complete" cannot be pressed yet, or null when it can. */
export function completeBlocked(card: Card): string | null {
  if (card.completed_at !== null) return null;
  if (card.waiting_for !== "nothing") return "Clear the wait first";
  if (card.kind !== "manual" && !card.ready) {
    const names = card.blockers.map((blocker) => blocker.key ?? blocker.title ?? blocker.reason);
    return names.length > 0 ? `Blocked by ${names.join(", ")}` : "Earlier work comes first";
  }
  return null;
}
