import { repositoryReading, type RunStepState } from "@/lib/runPhases";
import type { GenerationPurpose, GenerationRun, RunStage, RunTraceStep } from "@/lib/types";

/** The stages of a run's tree, in the order the server reaches them. */
export const STAGE_ORDER: readonly RunStage[] = [
  "documents",
  "repository",
  "writing",
  "checking",
  "saving",
];

/** One stage of the tree: its label, how far it got, and the steps the run recorded under it. */
export interface TraceStage {
  stage: RunStage;
  label: string;
  state: RunStepState;
  steps: RunTraceStep[];
}

type Purpose = GenerationPurpose;

function document(purpose: Purpose): string {
  return purpose === "roadmap" ? "RoadMap" : purpose === "qa" ? "QA instructions" : "analysis";
}

/** The brief for people reads the technical revision and writes the brief; no repository. */
const FOR_PEOPLE: Readonly<Partial<Record<RunStage, string>>> = {
  documents: "Reading the analysis",
  writing: "Writing for people",
  checking: "Checking coverage",
};

export function stageLabel(stage: RunStage, purpose: Purpose): string {
  if (purpose === "roadmap_human" && stage === "documents") return "Reading the RoadMap";
  const forPeople =
    purpose === "analysis_human" || purpose === "roadmap_human" ? FOR_PEOPLE[stage] : undefined;
  if (forPeople) return forPeople;
  switch (stage) {
    case "documents":
      return "Reading the Loop's documents";
    case "repository":
      return "Reading the repository";
    case "writing":
      return `Writing the ${document(purpose)}`;
    case "checking":
      return "Checking the answer";
    case "saving":
      return "Saving";
  }
}

/** A run that never reads a repository: QA instructions and the analysis written for people. */
function readsRepository(purpose: Purpose): boolean {
  return purpose === "analysis" || purpose === "roadmap";
}

function inFlight(run: Pick<GenerationRun, "status">): boolean {
  return run.status === "queued" || run.status === "running";
}

/**
 * Whether a run is shown as its tree: it recorded steps, or it is working and will. A run recorded
 * before the trace existed (an empty one that has finished) keeps the three fixed phases.
 */
export function hasTree(run: Pick<GenerationRun, "status" | "trace">): boolean {
  if (run.trace === undefined) return false;
  return run.trace.length > 0 || inFlight(run);
}

/**
 * The tree's stages with their steps and states.
 *
 * Every stage the purpose passes through is listed, so a person sees what comes next; one the run has
 * not reached yet is `pending` and has no steps. The stage the run is in is `active`, one it left
 * `done`; a stage with an error step is `failed`, one that hit a limit is `warning`, and the
 * repository stage of a board without repositories is `skipped` — a tick there would claim code was
 * read. The repository stage is `failed` when no repository could be read and `warning` when one of
 * several could not, whatever its steps say, so an older run's quiet "could not read" step never
 * shows a tick either. A run that failed without naming where fails the last stage it reached.
 */
export function traceStages(purpose: Purpose, run: GenerationRun): TraceStage[] {
  const steps = run.trace ?? [];
  const stages = STAGE_ORDER.filter((stage) => readsRepository(purpose) || stage !== "repository");
  const reached = stages.filter((stage) => steps.some((step) => step.stage === stage));
  const last = reached.at(-1);
  const anyError = steps.some((step) => step.kind === "error");
  return stages.map((stage, index) => {
    const own = steps.filter((step) => step.stage === stage);
    let state: RunStepState = "pending";
    if (own.length > 0) {
      state = stage === last && inFlight(run) ? "active" : "done";
      if (own.some((step) => step.kind === "error")) state = "failed";
      else if (stage === last && run.status === "failed" && !anyError) state = "failed";
      else if (own.some((step) => step.kind === "limit") && state === "done") state = "warning";
      if (stage === "repository") state = repositoryState(state, run);
    } else if (inFlight(run) && last === undefined && index === 0) {
      state = "active"; // started, and nothing recorded yet
    }
    return { stage, label: stageLabel(stage, purpose), state, steps: own };
  });
}

/** The repository stage by what the run could read; a stage still working or that ended the run
 * keeps its own state. */
function repositoryState(state: RunStepState, run: GenerationRun): RunStepState {
  if (state === "active") return state;
  const reading = repositoryReading(run);
  if (reading === "none") return state === "done" ? "skipped" : state;
  if (reading === "unread") return "failed";
  if (reading === "partial")
    return state === "failed" && run.status === "failed" ? state : "warning";
  return state;
}

/** What a run read through the tools: tool calls, distinct files read and searches. */
export function traceCounts(steps: readonly RunTraceStep[] | undefined): {
  toolCalls: number;
  files: number;
  searches: number;
} {
  const files = new Set<string>();
  let toolCalls = 0;
  let searches = 0;
  for (const step of steps ?? []) {
    if (step.kind !== "tool") continue;
    toolCalls += 1;
    if (step.tool === "search") searches += 1;
    if (step.tool === "read_file") step.answer?.files_read?.forEach((path) => files.add(path));
  }
  return { toolCalls, files: files.size, searches };
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : noun.endsWith("h") ? "es" : "s"}`;
}

/** "read 23 files, 4 searches" for a run whose model read through tools; null for any other run. */
export function describeRunReading(run: GenerationRun): string | null {
  const { toolCalls, files, searches } = traceCounts(run.trace);
  if (toolCalls === 0) return null;
  return `read ${plural(files, "file")}, ${plural(searches, "search")}`;
}
