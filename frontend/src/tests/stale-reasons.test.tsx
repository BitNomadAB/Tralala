import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { STALE_REASON_TEXT, staleReasonText } from "@/features/loops/loopUi";
import { PlanDocumentPanel } from "@/features/loops/PlanDocumentPanel";
import { emptyDocument } from "./msw/loops";

/** Every code `stale_reasons` in backend/app/services/loops_stage.py can produce. */
const BACKEND_CODES = [
  "info_missing",
  "info_changed",
  "analysis_ai_missing",
  "analysis_ai_changed",
  "analysis_missing",
  "analysis_changed",
  "roadmap_ai_missing",
  "roadmap_ai_changed",
  "upstream_stale",
  "approval_superseded",
];

function renderStale(reasons: string[]) {
  render(
    <PlanDocumentPanel
      kind="analysis"
      document={{
        ...emptyDocument("analysis"),
        state: "stale",
        stale: true,
        stale_reasons: reasons,
      }}
    />,
  );
}

describe("why a document needs regeneration", () => {
  it("reads as sentences, each keeping its code in the title", () => {
    renderStale(["info_changed", "analysis_ai_changed", "upstream_stale", "analysis_ai_missing"]);

    expect(screen.getByText("Info changed after this was written.")).toHaveAttribute(
      "title",
      "info_changed",
    );
    expect(screen.getByText("The AI analysis changed after this was written.")).toHaveAttribute(
      "title",
      "analysis_ai_changed",
    );
    expect(screen.getByText("An earlier document needs regeneration first.")).toHaveAttribute(
      "title",
      "upstream_stale",
    );
    expect(screen.getByText("The AI analysis has not been generated.")).toHaveAttribute(
      "title",
      "analysis_ai_missing",
    );
    // The codes themselves are no longer the text a person reads.
    expect(screen.queryByText(/info_changed/)).not.toBeInTheDocument();
  });

  it("says a repeated reason once and shows an unknown code as it is", () => {
    renderStale(["approval_superseded", "approval_superseded", "brand_new_reason"]);

    expect(
      screen.getAllByText("The approval was for an earlier revision; this one needs a new review."),
    ).toHaveLength(1);
    expect(screen.getByText("brand_new_reason")).toHaveAttribute("title", "brand_new_reason");
  });

  it("shows no line when nothing is stale", () => {
    renderStale([]);
    expect(screen.queryByText(/Needs regeneration/)).not.toBeInTheDocument();
  });

  it("has a sentence for every code the server produces", () => {
    for (const code of BACKEND_CODES) {
      expect(staleReasonText(code)).not.toBe(code);
      expect(staleReasonText(code)).toMatch(/^[A-Z].*\.$/);
    }
    expect(Object.keys(STALE_REASON_TEXT).sort()).toEqual([...BACKEND_CODES].sort());
    expect(staleReasonText("something_else")).toBe("something_else");
  });
});
