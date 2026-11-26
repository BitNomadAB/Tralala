import { describe, expect, it } from "vitest";
import { summarisable, tileCounts, waitingRows } from "@/features/boards/boardSummaries";
import { loopHref, loopNextAction, STAGE_WORDS } from "@/features/loops/loopNextAction";
import type { LoopSummary } from "@/lib/types";
import { board, summary } from "./msw/boards";

const WRITTEN = {
  info: "approved r1",
  analysis_ai: "empty",
  analysis: "empty",
  roadmap_ai: "empty",
  roadmap: "empty",
};

/** The fields a person sees: the line, the button, whether it is a decision and the tab. */
function shown(row: LoopSummary) {
  const action = loopNextAction(row);
  return [action.waiting, action.label, action.decision, action.tab];
}

describe("a Loop's next action for a person", () => {
  it("asks for the Info, then the analysis, of a draft", () => {
    expect(shown(summary("a", "A"))).toEqual(["Waits for its Info", "Write Info", false, "plan"]);
    expect(shown(summary("a", "A", { documents: WRITTEN, waiting_on: "agent" }))).toEqual([
      "Waits for the analysis",
      "Ask for analysis",
      false,
      "plan",
    ]);
  });

  it("makes a review waiting for a person a decision, and one waiting for a new document not", () => {
    expect(shown(summary("a", "A", { stage: "analysis_review", waiting_on: "person" }))).toEqual([
      "Waits for you to approve the analysis",
      "Approve analysis",
      true,
      "plan",
    ]);
    expect(shown(summary("a", "A", { stage: "analysis_review", waiting_on: "agent" }))).toEqual([
      "Waits for a new analysis",
      "Ask for analysis",
      false,
      "plan",
    ]);
    expect(shown(summary("a", "A", { stage: "roadmap_review", waiting_on: "person" }))).toEqual([
      "Waits for you to approve the RoadMap",
      "Approve RoadMap",
      true,
      "plan",
    ]);
    expect(shown(summary("a", "A", { stage: "roadmap_review", waiting_on: "agent" }))[0]).toBe(
      "Waits for a new RoadMap",
    );
  });

  it("words planning, replanning and QA", () => {
    expect(shown(summary("a", "A", { stage: "planning", waiting_on: "agent" }))).toEqual([
      "Waits for the RoadMap",
      "Ask for RoadMap",
      false,
      "plan",
    ]);
    // A RoadMap handed in keeps the Loop in planning: the server says a person reviews it.
    expect(shown(summary("a", "A", { stage: "planning", waiting_on: "person" }))).toEqual([
      "Waits for you to approve the RoadMap",
      "Approve RoadMap",
      true,
      "plan",
    ]);
    expect(shown(summary("a", "A", { stage: "replanning", waiting_on: "agent" }))[1]).toBe(
      "Ask for RoadMap",
    );
    expect(shown(summary("a", "A", { stage: "awaiting_qa" }))).toEqual([
      "Waits for you to accept QA",
      "Finalize Loop",
      true,
      "kanban",
    ]);
  });

  it("follows the server's order in delivery: answers, ready work, a person's task, blocked, done", () => {
    const delivery = (
      tickets: Partial<LoopSummary["tickets"]>,
      waiting: LoopSummary["waiting_on"] = "person",
    ) => shown(summary("a", "A", { stage: "in_progress", waiting_on: waiting, tickets }));
    expect(delivery({ needs_input: 2, needs_person: 3, ready: 1, total: 5 })).toEqual([
      "Waits for your answer on 2 Tickets",
      "Clear the wait",
      true,
      "kanban",
    ]);
    expect(delivery({ ready: 3, needs_person: 1, total: 3 }, "anyone")).toEqual([
      "2 Tickets ready to start",
      null,
      false,
      "kanban",
    ]);
    expect(delivery({ ready: 1, needs_person: 1, total: 2, completed: 1 })).toEqual([
      "Waits for you to confirm 1 Ticket",
      "Confirm Ticket",
      true,
      "kanban",
    ]);
    expect(delivery({ blocked: 1, total: 2, completed: 1 }, "anyone")).toEqual([
      "1 Ticket waiting for earlier work",
      null,
      false,
      "kanban",
    ]);
    expect(delivery({ total: 2, completed: 2 })).toEqual([
      "Waits for you to accept the work",
      "Accept work",
      true,
      "kanban",
    ]);
    // A plan held up for another reason the counts do not show.
    expect(delivery({ total: 2, completed: 1 })).toEqual([
      "Waits for a person",
      "Open Loop",
      false,
      "kanban",
    ]);
  });

  it("asks a person to close a Loop without a plan once every Ticket is done, and not before", () => {
    const fast = (
      stage: LoopSummary["stage"],
      tickets: Partial<LoopSummary["tickets"]>,
      waiting: LoopSummary["waiting_on"] = "person",
    ) => shown(summary("a", "A", { stage, without_plan: true, waiting_on: waiting, tickets }));
    // While something is open, the delivery lines are the same as with a plan.
    expect(fast("ready", { ready: 1, total: 1 }, "anyone")).toEqual([
      "1 Ticket ready to start",
      null,
      false,
      "kanban",
    ]);
    expect(
      fast("in_progress", { needs_input: 1, needs_person: 1, total: 2, completed: 1 }),
    ).toEqual(["Waits for your answer on 1 Ticket", "Clear the wait", true, "kanban"]);
    expect(fast("in_progress", { blocked: 1, total: 2, completed: 1 }, "anyone")[0]).toBe(
      "1 Ticket waiting for earlier work",
    );
    // Every Ticket done: one decision closes it, whoever the server says it waits for.
    for (const stage of ["ready", "in_progress"] as const) {
      expect(fast(stage, { total: 2, completed: 2 })).toEqual([
        "Waits for you to close the Loop",
        "Close Loop",
        true,
        "kanban",
      ]);
    }
    expect(fast("in_progress", { total: 1, completed: 1 }, "anyone")[1]).toBe("Close Loop");
    // Completed, it is finished like any other Loop.
    expect(fast("completed", { total: 2, completed: 2 }, "nobody")).toEqual([
      "Completed",
      null,
      false,
      "kanban",
    ]);
  });

  it("keeps a planned Loop's words when every Ticket is done", () => {
    const planned = summary("a", "A", {
      stage: "in_progress",
      waiting_on: "person",
      tickets: { total: 2, completed: 2 },
    });
    expect(shown(planned)).toEqual([
      "Waits for you to accept the work",
      "Accept work",
      true,
      "kanban",
    ]);
  });

  it("offers nothing on a finished Loop", () => {
    expect(shown(summary("a", "A", { stage: "completed", waiting_on: "nobody" }))).toEqual([
      "Completed",
      null,
      false,
      "kanban",
    ]);
    expect(shown(summary("a", "A", { stage: "cancelled", waiting_on: "nobody" }))[1]).toBeNull();
  });

  it("names every stage in a person's words and links to a tab", () => {
    expect(STAGE_WORDS.analysis_review).toBe("Analysis review");
    expect(STAGE_WORDS.roadmap_review).toBe("Planning");
    expect(STAGE_WORDS.in_progress).toBe("In progress");
    expect(loopHref("b 1", "l/1", "plan")).toBe("/boards/b%201/loops/l%2F1?tab=plan");
    expect(loopHref("b", "l")).toBe("/boards/b/loops/l");
  });
});

describe("the dashboard's summaries", () => {
  const review = summary("r", "Review", { stage: "analysis_review", waiting_on: "person" });
  const done = summary("d", "Done", { stage: "completed", waiting_on: "nobody" });

  it("lists only an active board's decisions, in the boards' order", () => {
    const active = board("b1", "One");
    const archived = board("b2", "Two", { status: "archived" });
    const second = board("b3", "Three");
    const entries = new Map([
      ["b1", { loops: [summary("x", "Draft"), review], pending: false, failed: false }],
      ["b2", { loops: [review], pending: false, failed: false }],
      ["b3", { loops: [review], pending: false, failed: false }],
    ]);
    const rows = waitingRows([active, archived, second], entries);
    expect(rows.map((row) => `${row.board.name}/${row.loop.name}`)).toEqual([
      "One/Review",
      "Three/Review",
    ]);
  });

  it("lists a Loop in planning whose RoadMap waits for a person's review", () => {
    const handedIn = summary("p", "Plan", { stage: "planning", waiting_on: "person" });
    const asked = summary("q", "Asked", { stage: "planning", waiting_on: "agent" });
    const entries = new Map([["b1", { loops: [asked, handedIn], pending: false, failed: false }]]);
    const rows = waitingRows([board("b1", "One")], entries);
    expect(rows.map((row) => [row.loop.name, row.action.label, row.action.tab])).toEqual([
      ["Plan", "Approve RoadMap", "plan"],
    ]);
  });

  it("counts open Loops and decisions, none on a read-only board", () => {
    expect(tileCounts([review, done, summary("x", "Draft")], false)).toEqual({
      open: 2,
      waiting: 1,
    });
    expect(tileCounts([review], true)).toEqual({ open: 1, waiting: 0 });
  });

  it("lists a Loop without a plan whose Tickets are all done as waiting to be closed", () => {
    const closing = summary("c", "Typos", {
      stage: "in_progress",
      without_plan: true,
      tickets: { total: 3, completed: 3 },
    });
    const working = summary("w", "Small fixes", {
      stage: "ready",
      without_plan: true,
      waiting_on: "anyone",
      tickets: { ready: 1, total: 1 },
    });
    const active = board("b1", "One");
    const entries = new Map([["b1", { loops: [working, closing], pending: false, failed: false }]]);
    const rows = waitingRows([active], entries);
    expect(rows.map((row) => [row.loop.name, row.action.waiting, row.action.label])).toEqual([
      ["Typos", "Waits for you to close the Loop", "Close Loop"],
    ]);
    expect(tileCounts([working, closing], false)).toEqual({ open: 2, waiting: 1 });
  });

  it("asks only a board that can be opened", () => {
    expect(summarisable(board("a", "A"))).toBe(true);
    expect(summarisable(board("a", "A", { status: "archived" }))).toBe(true);
    expect(summarisable(board("a", "A", { status: "migration_failed" }))).toBe(false);
  });
});
