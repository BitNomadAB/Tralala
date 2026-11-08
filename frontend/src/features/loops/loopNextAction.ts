import type { LoopStage, LoopSummary } from "@/lib/types";

/** The Loop page's tabs (`?tab=`; the Kanban is the default and needs none). */
export type LoopTab = "kanban" | "plan" | "notes";

/** What a Loop needs next, worded for a person: the line, the button and where it leads. */
export interface LoopNextAction {
  /** "Waits for you to approve the analysis", "2 Tickets ready to start", "Completed". */
  waiting: string;
  /** The button's words, or null when the person has nothing to do (the row still opens the Loop). */
  label: string | null;
  /**
   * True for a decision only a person makes (approve the analysis or the RoadMap, confirm a
   * Ticket, clear a wait, accept the work, finalize the Loop): such a Loop is listed under
   * "Waits for you" on the dashboard.
   */
  decision: boolean;
  tab: LoopTab;
}

/** The words a person reads for each stage (the stage chip). */
export const STAGE_WORDS: Record<LoopStage, string> = {
  draft: "Draft",
  analysis_review: "Analysis review",
  planning: "Planning",
  roadmap_review: "Planning",
  ready: "In progress",
  in_progress: "In progress",
  replanning: "Planning",
  awaiting_qa: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

/** A finished Loop is read-only and waits for nobody. */
export function isFinished(stage: LoopStage): boolean {
  return stage === "completed" || stage === "cancelled";
}

/** "1 Ticket" or "3 Tickets". */
export function tickets(count: number): string {
  return count === 1 ? "1 Ticket" : `${count} Tickets`;
}

function act(
  waiting: string,
  label: string | null,
  tab: LoopTab,
  decision = false,
): LoopNextAction {
  return { waiting, label, decision, tab };
}

/** A document's state from the summary's "approved r3" / "empty". */
function documentState(summary: LoopSummary, kind: keyof LoopSummary["documents"]): string {
  return summary.documents[kind].split(" ")[0] ?? "";
}

function review(summary: LoopSummary, document: "analysis" | "RoadMap"): LoopNextAction {
  const ask = document === "analysis" ? "Ask for analysis" : "Ask for RoadMap";
  if (summary.waiting_on === "person") {
    return act(`Waits for you to approve the ${document}`, `Approve ${document}`, "plan", true);
  }
  return act(`Waits for a new ${document}`, ask, "plan");
}

/** Delivery: the server's order (needs input, ready, a person's task, blocked, all done). */
function delivery(summary: LoopSummary): LoopNextAction {
  const counts = summary.tickets;
  const personTasks = counts.needs_person - counts.needs_input;
  if (counts.needs_input > 0) {
    return act(
      `Waits for your answer on ${tickets(counts.needs_input)}`,
      "Clear the wait",
      "kanban",
      true,
    );
  }
  if (counts.ready > personTasks) {
    return act(`${tickets(counts.ready - personTasks)} ready to start`, null, "kanban");
  }
  if (personTasks > 0) {
    return act(
      `Waits for you to confirm ${tickets(personTasks)}`,
      "Confirm Ticket",
      "kanban",
      true,
    );
  }
  if (counts.blocked > 0) {
    return act(`${tickets(counts.blocked)} waiting for earlier work`, null, "kanban");
  }
  if (summary.waiting_on === "person" && counts.completed === counts.total) {
    return act("Waits for you to accept the work", "Accept work", "kanban", true);
  }
  return act("Waits for a person", "Open Loop", "kanban");
}

/**
 * What a Loop needs next, from the summary the server gives (`loop_summaries`): the line the
 * board page and the dashboard show, the person's button and the tab it opens. The server's own
 * sentence (`next`) is written for a worker and names tools, so the words here are the UI's.
 */
export function loopNextAction(summary: LoopSummary): LoopNextAction {
  switch (summary.stage) {
    case "completed":
      return act("Completed", null, "kanban");
    case "cancelled":
      return act("Cancelled", null, "kanban");
    case "draft":
      return documentState(summary, "info") === "empty"
        ? act("Waits for its Info", "Write Info", "plan")
        : act("Waits for the analysis", "Ask for analysis", "plan");
    case "analysis_review":
      return review(summary, "analysis");
    case "planning":
      return act("Waits for the RoadMap", "Ask for RoadMap", "plan");
    case "roadmap_review":
      return review(summary, "RoadMap");
    case "replanning":
      return act("The Info changed: the RoadMap is planned again", "Ask for RoadMap", "plan");
    case "awaiting_qa":
      return act("Waits for you to accept QA", "Finalize Loop", "kanban", true);
    case "ready":
    case "in_progress":
      return delivery(summary);
  }
}

/** The Loop page, on the tab a next action needs (`?tab=plan`; the Kanban needs none). */
export function loopHref(boardId: string, loopId: string, tab: LoopTab = "kanban"): string {
  const page = `/boards/${encodeURIComponent(boardId)}/loops/${encodeURIComponent(loopId)}`;
  return tab === "kanban" ? page : `${page}?tab=${tab}`;
}
