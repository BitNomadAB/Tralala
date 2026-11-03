import { AlertTriangle, Check, Loader2, Minus, X } from "lucide-react";
import {
  failedStepKey,
  repositoryOutcome,
  runFailureJson,
  runSteps,
  type RunStep,
} from "@/lib/runPhases";
import type { GenerationRun } from "@/lib/types";

/** What the step achieved, not what it was supposed to do: a skipped step says so. */
function stepCaption(step: RunStep): string {
  if (step.key === "analysing_repository") {
    if (step.state === "skipped") return "Skipped: no code was sent to the model";
    if (step.state === "warning") return "Only part of the snapshot could be read";
  }
  return step.caption;
}

/**
 * The steps a generation run passes through, with the failing step's own JSON.
 *
 * Generation is one background call, so a person watching the dialog otherwise sees a disabled button
 * and nothing else. The server records the step it reached; this renders that step, the ones before it
 * as done, and — when it failed — the step it died on carrying the provider's answer verbatim.
 */
export function RunPhases({
  purpose,
  run,
  onDismiss,
  compact = false,
}: {
  purpose: "analysis" | "roadmap";
  run: GenerationRun;
  onDismiss?: (() => void) | undefined;
  compact?: boolean;
}) {
  const steps = runSteps(purpose, run);
  const failedKey = failedStepKey(run);
  const failureJson = runFailureJson(run);
  const repositories = repositoryOutcome(run);
  const running = run.status === "queued" || run.status === "running";

  return (
    <section
      aria-label="Generation progress"
      aria-live="polite"
      className={
        compact
          ? "flex flex-col gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2"
          : "flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-2xl"
      }
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className={`font-semibold ${compact ? "text-[11px]" : "text-sm"}`}>
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
      <ol
        className={
          compact ? "flex flex-row flex-wrap gap-2 text-[11px]" : "flex flex-col gap-2 text-xs"
        }
      >
        {steps.map((step, index) => {
          const tone =
            step.state === "failed"
              ? "text-[var(--destructive)]"
              : step.state === "warning"
                ? "text-[var(--warning)]"
                : step.state === "active"
                  ? "text-[var(--primary)]"
                  : step.state === "done"
                    ? "text-[var(--success)]"
                    : "text-[var(--muted-foreground)]";
          return (
            <li key={step.key} className="flex flex-col gap-1">
              <div className={`flex items-start gap-2 ${tone}`}>
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-current text-[10px]">
                  {step.state === "done" ? (
                    <Check size={10} />
                  ) : step.state === "failed" ? (
                    <X size={10} />
                  ) : step.state === "warning" ? (
                    <AlertTriangle size={10} />
                  ) : step.state === "skipped" ? (
                    <Minus size={10} />
                  ) : step.state === "active" ? (
                    <Loader2 size={10} className="animate-spin" />
                  ) : (
                    index + 1
                  )}
                </span>
                <div className="flex flex-col">
                  <span className="font-medium">{step.label}</span>
                  {compact ? null : (
                    <span className="text-[11px] text-[var(--muted-foreground)]">
                      {stepCaption(step)}
                    </span>
                  )}
                </div>
              </div>
              {step.key === "analysing_repository" && repositories.kind !== "waiting" ? (
                <p className="ml-6 text-[11px] text-[var(--muted-foreground)]">
                  {repositories.kind === "none"
                    ? "No enabled repository is linked to this board."
                    : repositories.lines.join("; ")}
                </p>
              ) : null}
              {step.key === "analysing_repository" &&
              repositories.kind === "waiting" &&
              step.state === "active" ? (
                <p className="ml-6 text-[11px] italic text-[var(--muted-foreground)]">
                  Fetching the linked repositories…
                </p>
              ) : null}
              {failureJson && step.key === failedKey ? (
                <pre className="ml-6 overflow-x-auto rounded-md border border-[var(--destructive)] bg-[var(--surface-raised)] p-2 text-[10px] leading-relaxed text-[var(--foreground)] scrollbar-thin">
                  {failureJson}
                </pre>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
