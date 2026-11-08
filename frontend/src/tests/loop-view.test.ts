import { describe, expect, it } from "vitest";
import { decisionShown, loopDecision } from "@/features/loops/loopDecision";
import { loopNextAction } from "@/features/loops/loopNextAction";
import { parseDocument, parseTab, viewParams } from "@/features/loops/useLoopView";
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
