import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { KeptCandidate } from "@/features/loops/KeptCandidate";
import { PlanDocumentPanel } from "@/features/loops/PlanDocumentPanel";
import { RoadmapPhases } from "@/features/loops/RoadmapPhases";
import { RoadmapReview } from "@/features/loops/RoadmapReview";
import { RunPhases } from "@/features/loops/RunPhases";
import type { LoopDocument } from "@/lib/types";
import { DOCUMENTS, emptyDocument, generationRun, NOW } from "./msw/loops";
import { renderLoopPage } from "./renderLoopPage";

const INFO: LoopDocument = {
  ...emptyDocument("info"),
  state: "ready_for_review",
  current_revision_id: "info-rev-2",
  current_revision_number: 2,
  current_created_at: NOW,
  current_content: "Sessions expire after 30 minutes.",
  approved_revision_id: "info-rev-1",
  approved_revision_number: 1,
  approved_content: "Sessions expire.",
};

/** A box a keyboard can reach and scroll: a named group in the tab order (WCAG 2.1.1). */
function expectScrollBox(name: string) {
  expect(screen.getByRole("group", { name })).toHaveAttribute("tabindex", "0");
}

describe("the plan's scroll boxes", () => {
  it("lets a keyboard reach a document's text and its approved baseline", () => {
    render(<PlanDocumentPanel kind="info" document={INFO} />);
    expectScrollBox("Info text");
    expectScrollBox("Approved baseline r1");
  });

  it("lets a keyboard reach the RoadMap's raw JSON, a kept result and a run's error", async () => {
    const technical: LoopDocument = {
      ...emptyDocument("roadmap_ai"),
      current_revision_number: 1,
      current_content: '{ "phases": [] }',
    };
    render(<RoadmapReview documents={{ ...DOCUMENTS, roadmap_ai: technical }} />);
    await userEvent.setup().click(screen.getByRole("tab", { name: "Raw text" }));
    expectScrollBox("The plan as JSON");

    const kept = generationRun("failed", "generating", {
      error_code: "generation_input_changed",
      output: { stale_candidate: { schema_version: 1, outcome: "Expire idle sessions" } },
    });
    render(
      <KeptCandidate
        run={kept}
        scopeLabel="analysis"
        regenerateDisabled
        onRegenerate={() => undefined}
      />,
    );
    expectScrollBox("Kept analysis text");

    render(<RunPhases purpose="analysis" run={generationRun("failed", "generating")} />);
    expectScrollBox("The run's error as JSON");
  });
});

describe("text a person decides on is never cut off", () => {
  it("wraps a Phase objective instead of truncating it", () => {
    const objective = "Expire idle sessions after thirty minutes on every device ".repeat(4).trim();
    render(
      <RoadmapPhases phases={[{ id: "p1", number: 1, name: "Expiry", objective, tickets: [] }]} />,
    );
    const line = screen.getByText(objective);
    expect(line).not.toHaveClass("truncate");
    expect(line).toHaveClass("break-words");
  });

  it("wraps the Loop page's title", async () => {
    await renderLoopPage("", "in_progress", {});
    const title = await screen.findByRole("heading", { level: 1 });
    expect(title).not.toHaveClass("truncate");
    expect(title).toHaveClass("break-words");
  });
});
