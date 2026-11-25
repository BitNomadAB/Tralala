import { describe, expect, it, vi } from "vitest";
import {
  completionMenuItems,
  decisionShown,
  loopDecision,
  NOTHING_TO_FINALIZE,
} from "@/features/loops/loopDecision";
import { loopNextAction } from "@/features/loops/loopNextAction";
import { parseDocument, parseTab, stageDocument, viewParams } from "@/features/loops/useLoopView";
import { summary } from "./msw/boards";

describe("the Loop page's view in the URL", () => {
  it("reads the tab, the Kanban when it names none or an unknown one", () => {
    expect(parseTab("plan")).toBe("plan");
    expect(parseTab("notes")).toBe("notes");
    expect(parseTab(null)).toBe("kanban");
    expect(parseTab("files")).toBe("kanban");
  });

  it("opens the Plan tab on the named document, else on the one the stage works on", () => {
    expect(parseDocument("roadmap", "draft")).toBe("roadmap");
    expect(parseDocument(null, "draft")).toBe("info");
    expect(parseDocument(null, "analysis_review")).toBe("analysis");
    expect(parseDocument("nonsense", "roadmap_review")).toBe("roadmap");
    expect(parseDocument(null, "in_progress")).toBe("roadmap");
  });

  it("opens the Plan tab of a Loop without a plan on its Info, which has no RoadMap", () => {
    expect(stageDocument("ready", true)).toBe("info");
    expect(stageDocument("in_progress", true)).toBe("info");
    expect(stageDocument("completed", true)).toBe("info");
    expect(parseDocument(null, "in_progress", true)).toBe("info");
    // A named document still wins, and a planned Loop keeps its stage's document.
    expect(parseDocument("roadmap", "in_progress", true)).toBe("roadmap");
    expect(stageDocument("in_progress")).toBe("roadmap");
    expect(stageDocument("in_progress", false)).toBe("roadmap");
  });

  it("writes tab and doc and keeps the Ticket that is open", () => {
    const current = new URLSearchParams("card=card-1");
    expect(viewParams(current, "plan", "analysis").toString()).toBe(
      "card=card-1&tab=plan&doc=analysis",
    );
    const onPlan = new URLSearchParams("tab=plan&doc=info&card=card-1");
    // The Plan tab chosen again keeps its document; another tab drops it; the Kanban needs no tab.
    expect(viewParams(onPlan, "plan").toString()).toBe("tab=plan&doc=info&card=card-1");
    expect(viewParams(onPlan, "notes").toString()).toBe("tab=notes&card=card-1");
    expect(viewParams(onPlan, "kanban").toString()).toBe("card=card-1");
  });
});

describe("the header's one decision", () => {
  const next = (extra: Parameters<typeof summary>[2]) => loopNextAction(summary("l", "L", extra));

  it("reviews the analysis or the RoadMap on the Plan tab when the person approves it", () => {
    expect(loopDecision(next({ stage: "analysis_review" }))).toEqual({
      kind: "review",
      label: "Approve analysis",
      doc: "analysis",
    });
    expect(loopDecision(next({ stage: "roadmap_review" }))).toEqual({
      kind: "review",
      label: "Approve RoadMap",
      doc: "roadmap",
    });
  });

  it("finalizes through the completion dialog", () => {
    expect(loopDecision(next({ stage: "awaiting_qa" }))).toEqual({
      kind: "finalize",
      label: "Finalize Loop",
    });
    const accepted = next({
      stage: "in_progress",
      tickets: { completed: 2, total: 2 },
    });
    expect(loopDecision(accepted)).toEqual({ kind: "finalize", label: "Accept work" });
    const closing = next({
      stage: "in_progress",
      without_plan: true,
      tickets: { completed: 2, total: 2 },
    });
    expect(loopDecision(closing)).toEqual({ kind: "finalize", label: "Close Loop" });
  });

  it("offers nothing for a step that is not the Loop's decision", () => {
    expect(loopDecision(null)).toBeNull();
    // A generation, a Ticket's wait and a person's Ticket are not decided in the header.
    expect(loopDecision(next({ stage: "draft" }))).toBeNull();
    expect(loopDecision(next({ stage: "analysis_review", waiting_on: "agent" }))).toBeNull();
    expect(
      loopDecision(next({ stage: "in_progress", tickets: { needs_input: 1, needs_person: 1 } })),
    ).toBeNull();
    expect(
      loopDecision(next({ stage: "in_progress", tickets: { needs_person: 1, total: 1 } })),
    ).toBeNull();
    expect(loopDecision(next({ stage: "in_progress", tickets: { ready: 2 } }))).toBeNull();
    expect(loopDecision(next({ stage: "completed" }))).toBeNull();
  });

  it("hides a review while the Plan tab already shows that document", () => {
    const review = loopDecision(next({ stage: "analysis_review" }));
    expect(decisionShown(review, { tab: "plan", doc: "analysis" })).toBeNull();
    expect(decisionShown(review, { tab: "plan", doc: "info" })).toBe(review);
    expect(decisionShown(review, { tab: "kanban", doc: "analysis" })).toBe(review);
    const finalize = loopDecision(next({ stage: "awaiting_qa" }));
    expect(decisionShown(finalize, { tab: "plan", doc: "roadmap" })).toBe(finalize);
  });
});

describe("the Loop actions item that opens the completion dialog", () => {
  const item = (
    stage: Parameters<typeof completionMenuItems>[0]["stage"],
    withoutPlan: boolean,
    locked?: string,
  ) => {
    const open = vi.fn<() => void>();
    const items = completionMenuItems({ stage, without_plan: withoutPlan }, null, locked, open);
    return { items, open };
  };
  const shown = (items: ReturnType<typeof completionMenuItems>) =>
    items.map(({ label, disabled, hint }) => ({ label, disabled, hint }));

  it("is Close Loop for a Loop without a plan, and opens the dialog", () => {
    const { items, open } = item("in_progress", true);
    expect(shown(items)).toEqual([{ label: "Close Loop", disabled: false, hint: undefined }]);
    items[0]?.onSelect();
    expect(open).toHaveBeenCalledTimes(1);
    expect(shown(item("ready", true).items)[0]?.label).toBe("Close Loop");
  });

  it("shows a draft's Finalize Loop without offering it, and says why", () => {
    expect(shown(item("draft", false).items)).toEqual([
      { label: "Finalize Loop", disabled: true, hint: NOTHING_TO_FINALIZE },
    ]);
    expect(NOTHING_TO_FINALIZE).toBe("Nothing to finalize yet: add a Ticket or plan the Loop");
  });

  it("is today's Finalize Loop in every other stage, and read-only says so", () => {
    for (const stage of ["analysis_review", "planning", "in_progress", "awaiting_qa"] as const) {
      expect(shown(item(stage, false).items)).toEqual([
        { label: "Finalize Loop", disabled: false, hint: undefined },
      ]);
    }
    const locked = "The Loop is read-only";
    expect(shown(item("completed", false, locked).items)).toEqual([
      { label: "Finalize Loop", disabled: true, hint: locked },
    ]);
    expect(shown(item("completed", true, locked).items)).toEqual([
      { label: "Close Loop", disabled: true, hint: locked },
    ]);
  });

  it("is left out while the header's one button opens the dialog", () => {
    const open = () => undefined;
    const closing = loopDecision(
      loopNextAction(
        summary("l", "L", {
          stage: "in_progress",
          without_plan: true,
          tickets: { completed: 1, total: 1 },
        }),
      ),
    );
    expect(
      completionMenuItems({ stage: "in_progress", without_plan: true }, closing, undefined, open),
    ).toEqual([]);
    const review = loopDecision(loopNextAction(summary("l", "L", { stage: "analysis_review" })));
    expect(
      completionMenuItems(
        { stage: "analysis_review", without_plan: false },
        review,
        undefined,
        open,
      ),
    ).toHaveLength(1);
  });
});
