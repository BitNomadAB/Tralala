import { useAnnounceWhen } from "@/components/ui/useAnnounce";
import { runSteps, type RunStepState } from "@/lib/runPhases";
import { hasTree, traceStages } from "@/lib/runTrace";
import type { GenerationRun } from "@/lib/types";
import type { PlanScope, RunPurpose } from "./loopUi";

/** A step's state in words for a screen reader; on screen its mark and colour say it. */
export const STATE_WORDS: Record<RunStepState, string> = {
  done: "done",
  failed: "failed",
  warning: "done with a warning",
  active: "in progress",
  skipped: "skipped",
  pending: "not started",
};

/** A stage's colour by its state; `StageIcon` gives it a shape and `StateText` words. */
export const STATE_TONE: Record<RunStepState, string> = {
  failed: "text-[var(--destructive)]",
  warning: "text-[var(--warning)]",
  active: "text-[var(--primary)]",
  done: "text-[var(--success)]",
  skipped: "text-[var(--muted-foreground)]",
  pending: "text-[var(--muted-foreground)]",
};

/**
 * What a run panel describes: the run's own purpose, so a run keeps its stages when the person
 * opens another document while it works; the scope only for a purpose the panel has no stages for.
 */
export function runPurpose(scope: PlanScope, run: GenerationRun): RunPurpose {
  const purpose = run.purpose;
  return purpose === "analysis" ||
    purpose === "roadmap" ||
    purpose === "analysis_human" ||
    purpose === "roadmap_human"
    ? purpose
    : scope;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/**
 * The one line a screen reader hears about a working run, "Step 2 of 5: reading the repository":
 * it changes when the run reaches another stage, never with the steps inside one, so the panel
 * can grow every poll without being read out line by line. Null once the run has ended (its toast
 * says how) and while no stage is under way.
 */
export function runProgressLine(purpose: RunPurpose, run: GenerationRun): string | null {
  if (run.status !== "queued" && run.status !== "running") return null;
  const stages: readonly { label: string; state: RunStepState }[] = hasTree(run)
    ? traceStages(purpose, run)
    : runSteps(purpose, run);
  const index = stages.findIndex((stage) => stage.state === "active");
  const stage = stages[index];
  if (!stage) return null;
  return `Step ${index + 1} of ${stages.length}: ${lowerFirst(stage.label)}`;
}

/** Announces the run's progress line each time it changes (WCAG 4.1.3); call it once per page. */
export function useRunAnnouncement(scope: PlanScope, run: GenerationRun | null | undefined): void {
  const line = run ? runProgressLine(runPurpose(scope, run), run) : null;
  useAnnounceWhen(line !== null, line ?? "");
}

/** How close to its end a box counts as showing it: about two lines of the run's steps. */
const END_SLACK_PX = 32;

/** Whether a scrolled box shows its end, so new lines may keep it there. */
export function nearBottom(box: {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}): boolean {
  return box.scrollHeight - box.scrollTop - box.clientHeight <= END_SLACK_PX;
}
