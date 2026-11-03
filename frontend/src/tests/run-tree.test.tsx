import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunPhases } from "@/features/loops/RunPhases";
import type { RunTraceStep } from "@/lib/types";
import { generationRun } from "./msw/loops";

const AT = "2026-11-03T10:00:00Z";

const TRACE: RunTraceStep[] = [
  { stage: "documents", kind: "step", text: "Read the Loop's Info (revision 2)", at: AT },
  {
    stage: "repository",
    kind: "step",
    text: "Opened app @ aaaaaaaa for the model to read: 3 files, 120 bytes of text",
    at: AT,
  },
  { stage: "repository", kind: "note", text: "I'll start with the installation guide.", at: AT },
  {
    stage: "repository",
    kind: "tool",
    tool: "read_file",
    arguments: { path: "app/docs/install.md" },
    answer: { files_read: ["app/docs/install.md"], chars: 90 },
    text: "Read app/docs/install.md, lines 1–2 of 2",
    at: AT,
  },
];

function progress() {
  return screen.getByRole("region", { name: "Generation progress" });
}

describe("the run panel's process tree", () => {
  it("grows under its stages in plain words while the run works", () => {
    const { rerender } = render(
      <RunPhases
        purpose="analysis"
        run={generationRun("running", "generating", { trace: TRACE })}
      />,
    );
    const panel = progress();
    expect(within(panel).getByText("Working")).toBeInTheDocument();
    for (const label of [
      "Reading the Loop's documents",
      "Reading the repository",
      "Writing the analysis",
      "Checking the answer",
      "Saving",
    ]) {
      expect(within(panel).getByText(label)).toBeInTheDocument();
    }
    expect(within(panel).getByText("Read app/docs/install.md, lines 1–2 of 2")).toBeInTheDocument();
    // The model's own words are its note, quoted.
    expect(
      within(panel).getByText("“I'll start with the installation guide.”"),
    ).toBeInTheDocument();
    expect(within(panel).queryByText("Analysing repository")).toBeNull();

    const more: RunTraceStep[] = [
      ...TRACE,
      {
        stage: "writing",
        kind: "step",
        text: "The model wrote its answer after 1 tool call",
        at: AT,
      },
      {
        stage: "checking",
        kind: "repair",
        text: "The answer broke a rule: Phase dependency references an unknown Phase — asked the model to fix it",
        at: AT,
      },
    ];
    rerender(
      <RunPhases
        purpose="analysis"
        run={generationRun("running", "generating", { trace: more })}
      />,
    );
    expect(within(progress()).getByText(/asked the model to fix it/)).toBeInTheDocument();
  });

  it("keeps the tree after a failure, with the provider's answer as JSON", () => {
    const failed = generationRun("failed", "generating", {
      error_code: "provider_error",
      error_message: "The provider call failed: timeout",
      trace: [
        ...TRACE,
        { stage: "writing", kind: "error", text: "The provider call failed: timeout", at: AT },
      ],
    });
    render(<RunPhases purpose="analysis" run={failed} />);
    const panel = progress();
    expect(within(panel).getByText("Stopped")).toBeInTheDocument();
    expect(within(panel).getByText("The provider call failed: timeout")).toBeInTheDocument();
    expect(panel.querySelector("pre")?.textContent).toContain('"error_code": "provider_error"');
  });

  it("shows the stages and the newest step when compact", () => {
    render(
      <RunPhases
        purpose="roadmap"
        compact
        run={generationRun("running", "generating", { trace: TRACE })}
      />,
    );
    const panel = progress();
    expect(within(panel).getByText("Writing the RoadMap")).toBeInTheDocument();
    expect(within(panel).getByText("Read app/docs/install.md, lines 1–2 of 2")).toBeInTheDocument();
    expect(within(panel).queryByText("Read the Loop's Info (revision 2)")).toBeNull();
  });

  it("keeps the three fixed phases for a run recorded before the tree", () => {
    render(
      <RunPhases
        purpose="analysis"
        run={generationRun("completed", "generating", { trace: [] })}
      />,
    );
    expect(within(progress()).getByText("Generating analysis")).toBeInTheDocument();
  });
});
