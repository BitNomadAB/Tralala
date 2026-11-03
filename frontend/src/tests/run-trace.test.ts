import { describe, expect, it } from "vitest";
import { describeRunRepositories } from "@/lib/loopRuns";
import { describeRunReading, hasTree, traceCounts, traceStages } from "@/lib/runTrace";
import type { GenerationRun, RunTraceStep } from "@/lib/types";
import { generationRun } from "./msw/loops";

const AT = "2026-11-03T10:00:00Z";

function step(stage: RunTraceStep["stage"], text: string, extra: Partial<RunTraceStep> = {}) {
  return { stage, kind: "step", text, at: AT, ...extra } satisfies RunTraceStep;
}

function read(path: string): RunTraceStep {
  return step("repository", `Read ${path}, lines 1–9 of 9`, {
    kind: "tool",
    tool: "read_file",
    arguments: { path },
    answer: { files_read: [path], chars: 200 },
  });
}

const SEARCH = step("repository", "Searched *.md for 'install': 2 matches in 1 file", {
  kind: "tool",
  tool: "search",
  arguments: { pattern: "install", glob: "*.md" },
});

const TOOLS_RUN: RunTraceStep[] = [
  step("documents", "Read the Loop's Info (revision 1)"),
  step("repository", "Opened app @ aaaaaaaa for the model to read: 3 files, 120 bytes of text"),
  step("repository", "I'll read the guide first.", { kind: "note" }),
  read("app/README.md"),
  read("app/docs/install.md"),
  read("app/README.md"),
  SEARCH,
];

function run(status: GenerationRun["status"], trace: RunTraceStep[] | undefined, extra = {}) {
  return generationRun(status, "generating", { trace, ...extra });
}

describe("the run's process tree", () => {
  it("is shown for a run that recorded steps or is working, never for an older finished run", () => {
    expect(hasTree(run("running", []))).toBe(true);
    expect(hasTree(run("completed", TOOLS_RUN))).toBe(true);
    expect(hasTree(run("completed", []))).toBe(false);
    expect(hasTree(run("running", undefined))).toBe(false);
  });

  it("lists every stage the purpose passes through and marks how far the run got", () => {
    const stages = traceStages("analysis", run("running", TOOLS_RUN));
    expect(stages.map((stage) => [stage.label, stage.state])).toEqual([
      ["Reading the Loop's documents", "done"],
      ["Reading the repository", "active"],
      ["Writing the analysis", "pending"],
      ["Checking the answer", "pending"],
      ["Saving", "pending"],
    ]);
    expect(stages[1]?.steps).toHaveLength(6);
    expect(stages[2]?.steps).toEqual([]);
  });

  it("starts on the first stage before the server recorded a step", () => {
    const stages = traceStages("roadmap", run("queued", []));
    expect(stages.map((stage) => stage.state)).toEqual([
      "active",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
    expect(stages[2]?.label).toBe("Writing the RoadMap");
  });

  it("fails the stage that names the error, and warns on a limit the run reached", () => {
    const trace: RunTraceStep[] = [
      ...TOOLS_RUN,
      step("repository", "Reached the 60 tool calls this run allows", { kind: "limit" }),
      step("writing", "The provider call failed: timeout", { kind: "error" }),
      step("saving", "Nothing was saved: The provider call failed: timeout", { kind: "error" }),
    ];
    const states = traceStages("analysis", run("failed", trace)).map((stage) => stage.state);
    expect(states).toEqual(["done", "warning", "failed", "pending", "failed"]);
  });

  it("never ticks the repository stage of a board that links none", () => {
    const trace = [
      step("documents", "Read the Loop's Info (revision 1)"),
      step("repository", "No enabled repository is linked to this board; no code was read"),
      step("writing", "The model answered (900 characters)"),
    ];
    const completed = run("completed", trace, { source_revisions: { repositories: [] } });
    expect(traceStages("analysis", completed)[1]?.state).toBe("skipped");
  });

  it("leaves the repository stage out of QA instructions", () => {
    const stages = traceStages("qa", run("running", [step("documents", "Read")]));
    expect(stages.map((stage) => stage.stage)).toEqual([
      "documents",
      "writing",
      "checking",
      "saving",
    ]);
  });
});

describe("what a run read", () => {
  it("counts tool calls, distinct files and searches", () => {
    expect(traceCounts(TOOLS_RUN)).toEqual({ toolCalls: 4, files: 2, searches: 1 });
    expect(traceCounts(undefined)).toEqual({ toolCalls: 0, files: 0, searches: 0 });
  });

  it("says it on the based-on line of a run that read through tools", () => {
    const completed = run("completed", TOOLS_RUN, {
      source_revisions: {
        repositories: [
          {
            id: "repo-1",
            name: "app",
            branch: "main",
            commit_sha: "a".repeat(40),
            file_count: 3,
            truncated: false,
            reading: "tools",
            left_out: 0,
          },
        ],
      },
    });
    expect(describeRunReading(completed)).toBe("read 2 files, 1 search");
    expect(describeRunRepositories(completed)).toBe(
      "app @ aaaaaaaa, 3 files to read from — read 2 files, 1 search",
    );
  });

  it("says nothing of the kind for a run that sent a snapshot", () => {
    expect(describeRunReading(run("completed", [step("documents", "Read")]))).toBeNull();
  });
});
