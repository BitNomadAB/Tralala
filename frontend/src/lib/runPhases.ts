import type { GenerationRun } from "@/lib/types";

/** The steps a generation run passes through, in the order the server records them. */
export type RunPhaseKey = "reading_info" | "analysing_repository" | "generating";

export type RunStepState = "pending" | "active" | "done" | "failed";

export interface RunStep {
  key: RunPhaseKey;
  label: string;
  caption: string;
  state: RunStepState;
}

const ORDER: RunPhaseKey[] = ["reading_info", "analysing_repository", "generating"];

function labels(purpose: "analysis" | "roadmap"): Record<RunPhaseKey, string> {
  const document = purpose === "analysis" ? "analysis" : "RoadMap";
  return {
    reading_info: "Reading Info data",
    analysing_repository: "Analysing repository",
    generating: `Generating ${document}`,
  };
}

const CAPTIONS: Record<RunPhaseKey, string> = {
  reading_info: "The Loop's Info, goal and current plan",
  analysing_repository: "A bounded, read-only snapshot of the linked repositories",
  generating: "One provider call, then a schema check",
};

/**
 * Which steps are done, running and failed.
 *
 * The server records the step the run *reached*, so a step before the active one is finished, and on
 * failure the step it died on is the failed one — the panel must point at that step, not at the end.
 */
export function runSteps(
  purpose: "analysis" | "roadmap" | "qa",
  run?: Pick<GenerationRun, "status" | "phase"> | null,
): RunStep[] {
  const names = labels(purpose === "roadmap" ? "roadmap" : "analysis");
  const reached = run?.phase && ORDER.includes(run.phase as RunPhaseKey)
    ? (run.phase as RunPhaseKey)
    : null;
  const reachedIndex = reached ? ORDER.indexOf(reached) : -1;
  const failed = run?.status === "failed";
  const finished = run?.status === "completed";

  return ORDER.map((key, index) => {
    let state: RunStepState = "pending";
    if (failed && run?.phase === null && index === 0) {
      // A run rejected before its first step (no agent, closed Loop) still has to point somewhere.
      state = "failed";
    } else if (reachedIndex >= 0) {
      if (index < reachedIndex) state = "done";
      else if (index === reachedIndex) state = failed ? "failed" : finished ? "done" : "active";
    }
    return { key, label: names[key], caption: CAPTIONS[key], state };
  });
}

/** The failing step's own JSON, so a person can copy the provider's answer instead of retyping it. */
export function runFailureJson(run: Pick<GenerationRun, "status" | "phase" | "error_code" | "error_message">): string | null {
  if (run.status !== "failed") return null;
  return JSON.stringify(
    {
      status: run.status,
      phase: run.phase,
      error_code: run.error_code,
      error_message: run.error_message,
    },
    null,
    2,
  );
}

/** The step that shows the failure JSON, or null when nothing failed. */
export function failedStepKey(run: Pick<GenerationRun, "status" | "phase">): RunPhaseKey | null {
  if (run.status !== "failed") return null;
  return run.phase && ORDER.includes(run.phase as RunPhaseKey)
    ? (run.phase as RunPhaseKey)
    : ORDER[0];
}
