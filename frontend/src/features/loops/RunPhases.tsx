import { X } from "lucide-react";
import {
  failedStepKey,
  repositoryOutcome,
  runFailureJson,
  runSteps,
  type RunStep,
} from "@/lib/runPhases";
import { hasTree } from "@/lib/runTrace";
import type { GenerationRun } from "@/lib/types";
import type { RunPurpose } from "./loopUi";
import { STATE_TONE } from "./runStatus";
import { FailureJson, RunTree, StageIcon, StateText } from "./RunTree";
import { UnreadRepositories } from "./UnreadRepositories";

/** What the step achieved, not what it was supposed to do: a skipped step says so. */
function stepCaption(step: RunStep): string {
  if (step.key === "analysing_repository") {
    if (step.state === "skipped") return "Skipped: no code was sent to the model";
    if (step.state === "warning") return "Only part of the code could be read";
    if (step.state === "failed") return "Not read: no code was sent to the model";
  }
  return step.caption;
}

/**
 * What a generation run is doing, with the failing step's own JSON.
 *
 * A person watching the dialog otherwise sees a disabled button and nothing else. A run records its
 * process tree step by step (`RunTree`): every file the model read, every repair and every limit, in
 * plain words. A run recorded before the tree existed shows the step it reached, the ones before it
 * as done, and — when it failed — the step it died on carrying the provider's answer verbatim.
 * The section is not a live region: it grows every poll, and a screen reader would read each new
 * line. The page announces one line per stage instead (`useRunAnnouncement`).
 */
export function RunPhases({
  purpose,
  run,
  onDismiss,
  compact = false,
}: {
  purpose: RunPurpose;
  run: GenerationRun;
  onDismiss?: (() => void) | undefined;
  compact?: boolean;
}) {
  const failureJson = runFailureJson(run);
  const running = run.status === "queued" || run.status === "running";

  return (
    <section
      aria-label="Generation progress"
      className={
        compact
          ? "flex flex-col gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2"
          : "flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-2xl"
      }
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className={`font-semibold ${compact ? "text-xs" : "text-sm"}`}>
          {running ? "Working" : run.status === "completed" ? "Done" : "Stopped"}
        </h3>
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss progress"
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
          >
            <X size={14} />
          </button>
        ) : null}
      </div>
      <UnreadRepositories run={run} />
      {hasTree(run) ? (
        <RunTree purpose={purpose} run={run} compact={compact} failureJson={failureJson} />
      ) : (
        <PhaseList purpose={purpose} run={run} compact={compact} failureJson={failureJson} />
      )}
    </section>
  );
}

/** The three fixed phases of a run recorded before the process tree existed. */
function PhaseList({
  purpose,
  run,
  compact,
  failureJson,
}: {
  purpose: RunPurpose;
  run: GenerationRun;
  compact: boolean;
  failureJson: string | null;
}) {
  const steps = runSteps(purpose, run);
  const failedKey = failedStepKey(run);
  const repositories = repositoryOutcome(run);
  return (
    <ol className={`flex gap-2 text-xs ${compact ? "flex-row flex-wrap" : "flex-col"}`}>
      {steps.map((step, index) => {
        return (
          <li key={step.key} className="flex flex-col gap-1">
            <div className={`flex items-start gap-2 ${STATE_TONE[step.state]}`}>
              <StageIcon state={step.state} number={index + 1} />
              <div className="flex flex-col">
                <span className="font-medium">
                  {step.label}
                  <StateText state={step.state} />
                </span>
                {compact ? null : (
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {stepCaption(step)}
                  </span>
                )}
              </div>
            </div>
            {step.key === "analysing_repository" && repositories.kind !== "waiting" ? (
              <p className="ml-6 text-xs text-[var(--muted-foreground)]">
                {repositories.kind === "none"
                  ? "No enabled repository is linked to this board."
                  : repositories.lines.join("; ")}
              </p>
            ) : null}
            {step.key === "analysing_repository" &&
            repositories.kind === "waiting" &&
            step.state === "active" ? (
              <p className="ml-6 text-xs italic text-[var(--muted-foreground)]">
                Fetching the linked repositories…
              </p>
            ) : null}
            {failureJson && step.key === failedKey ? (
              <div className="ml-6">
                <FailureJson json={failureJson} />
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
