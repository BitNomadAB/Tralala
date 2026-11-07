import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunPhases } from "@/features/loops/RunPhases";
import { describeRunRepositories } from "@/lib/loopRuns";
import { traceStages } from "@/lib/runTrace";
import type { GenerationRunRepository, RunTraceStep } from "@/lib/types";
import { generationRun } from "./msw/loops";

const AT = "2026-11-03T10:00:00Z";
const CANNOT_SEE = "The key cannot see BitNomad: give it read access to the repository's contents";

function step(stage: RunTraceStep["stage"], text: string, kind: RunTraceStep["kind"] = "step") {
  return { stage, kind, text, at: AT } satisfies RunTraceStep;
}

const HIDDEN: GenerationRunRepository = {
  id: "r1",
  name: "BitNomad",
  branch: "main",
  commit_sha: null,
  file_count: 0,
  truncated: false,
  error: "not_found",
  problem: CANNOT_SEE,
};

/** The same entry as an older run recorded it: the code alone, no sentence. */
const { problem: _sentence, ...OLDER } = HIDDEN;

const READ: GenerationRunRepository = {
  id: "r2",
  name: "app",
  branch: "main",
  commit_sha: "a".repeat(40),
  file_count: 3,
  truncated: false,
  reading: "tools",
};

const AFTER: RunTraceStep[] = [
  step("writing", "The model answered (900 characters)"),
  step("checking", "The answer matches the schema"),
  step("saving", "Saved the analysis as a draft for a person to review and approve"),
];

/** A finished analysis whose repository step recorded `repository`, over `repositories`. */
function finished(repository: RunTraceStep[], repositories: GenerationRunRepository[]) {
  return generationRun("completed", "generating", {
    trace: [step("documents", "Read the Loop's Info (revision 1)"), ...repository, ...AFTER],
    source_revisions: { repositories },
  });
}

const UNREAD = finished(
  [
    step("repository", CANNOT_SEE, "error"),
    step(
      "repository",
      "No code was read: the run goes on from the Loop's documents alone",
      "error",
    ),
  ],
  [HIDDEN],
);

/** The repository stage's heading in the full panel. */
function repositoryStage() {
  const label = within(screen.getByRole("region", { name: "Generation progress" })).getByText(
    "Reading the repository",
  );
  const heading = label.parentElement;
  if (!heading) throw new Error("the stage has no heading");
  return heading;
}

describe("a run whose repository could not be read", () => {
  it("fails the repository stage and goes on with the rest", () => {
    expect(traceStages("analysis", UNREAD).map((stage) => stage.state)).toEqual([
      "done",
      "failed",
      "done",
      "done",
      "done",
    ]);
  });

  it("never ticks the stage of an older run whose step said only 'could not read'", () => {
    // The owner's run: the step was a plain one, and the stage showed a green check.
    const older = finished([step("repository", "Could not read BitNomad: not_found")], [OLDER]);
    expect(traceStages("analysis", older)[1]?.state).toBe("failed");
  });

  it("warns, rather than fails, when one of several repositories could not be read", () => {
    const partial = finished(
      [
        step("repository", "Opened app @ aaaaaaaa for the model to read: 3 files"),
        step("repository", CANNOT_SEE, "error"),
        step(
          "repository",
          "Not read: BitNomad; the run goes on with the rest of the code",
          "limit",
        ),
      ],
      [READ, HIDDEN],
    );
    expect(traceStages("analysis", partial)[1]?.state).toBe("warning");
  });

  it("shows the stage with a cross, never a check, and the step that says what to do", () => {
    render(<RunPhases purpose="analysis" run={UNREAD} />);
    const heading = repositoryStage();
    expect(heading.className).toContain("var(--destructive)");
    expect(heading.querySelector(".lucide-check")).toBeNull();
    expect(heading.querySelector(".lucide-x")).not.toBeNull();
    const panel = screen.getByRole("region", { name: "Generation progress" });
    expect(within(panel).getAllByText(CANNOT_SEE).length).toBeGreaterThan(0);
  });

  it("warns above the stages, compact too, that it was written without the code", () => {
    render(<RunPhases purpose="analysis" run={UNREAD} compact />);
    const note = screen.getByRole("note", { name: "Written without the code" });
    expect(within(note).getByText(CANNOT_SEE)).toBeInTheDocument();
  });

  it("carries no warning when the code was read", () => {
    render(
      <RunPhases
        purpose="analysis"
        run={finished([step("repository", "Opened app @ aaaaaaaa for the model")], [READ])}
      />,
    );
    expect(screen.queryByRole("note")).toBeNull();
    expect(repositoryStage().querySelector(".lucide-check")).not.toBeNull();
  });

  it("says on the based-on line, in words a person reads, that no code was read", () => {
    expect(describeRunRepositories(UNREAD)).toBe(
      `no code — written without the repository (${CANNOT_SEE})`,
    );
    const partial = finished([], [READ, HIDDEN]);
    expect(describeRunRepositories(partial)).toBe(
      `app @ aaaaaaaa, 3 files to read from; BitNomad — not read (${CANNOT_SEE})`,
    );
    expect(describeRunRepositories(UNREAD)).not.toContain("unavailable");
  });
});
