import { describeRunCost, describeRunRepositories } from "@/lib/loopRuns";
import type { GenerationRun } from "@/lib/types";
import type { PlanScope, RunPurpose } from "./loopUi";
import { RunPhases } from "./RunPhases";

/** The brief for people has stages of its own; any other run is its scope's. */
function runPurpose(scope: PlanScope, run: GenerationRun): RunPurpose {
  return run.purpose === "analysis_human" || run.purpose === "roadmap_human" ? run.purpose : scope;
}

interface RunPanelProps {
  scope: PlanScope;
  run: GenerationRun;
  onDismiss: (() => void) | undefined;
}

/** The run's steps under the button that started it, on screens too narrow for the panel beside. */
export function GenerationRunPanel({ scope, run, onDismiss }: RunPanelProps) {
  return (
    <div className="mt-2 2xl:hidden">
      <RunPhases purpose={runPurpose(scope, run)} run={run} compact onDismiss={onDismiss} />
    </div>
  );
}

/**
 * The run's steps beside the documents on a wide screen: the Plan tab's second column, and it
 * stays in view below the app bar while the page scrolls.
 */
export function GenerationRunAside({ scope, run, onDismiss }: RunPanelProps) {
  return (
    <aside className="sticky top-20 hidden self-start 2xl:block">
      <RunPhases purpose={runPurpose(scope, run)} run={run} onDismiss={onDismiss} />
    </aside>
  );
}

/** One line on the scope's last run: its outcome, when, by whom and from which repositories. */
export function LastRunStatus({
  scope,
  lastRun,
  loading,
}: {
  scope: PlanScope;
  lastRun: GenerationRun | undefined;
  loading: boolean;
}) {
  return (
    <p
      role="status"
      className={`mt-2 text-[11px] ${
        lastRun?.status === "failed"
          ? "text-[var(--destructive)]"
          : "text-[var(--muted-foreground)]"
      }`}
    >
      {loading ? (
        "Checking the last run…"
      ) : lastRun ? (
        <>
          Last {scope} run {lastRun.status}
          {lastRun.error_message ? ` — ${lastRun.error_message}` : ""} ·{" "}
          {new Date(lastRun.created_at).toLocaleString()}
          {lastRun.agent_name ? ` · ${lastRun.agent_name}` : ""}
          {describeRunCost(lastRun)?.replace(/^/, " · ") ?? ""}
          {describeRunRepositories(lastRun) ? (
            <>
              {" · based on "}
              {describeRunRepositories(lastRun)}
            </>
          ) : null}
        </>
      ) : (
        `No ${scope} run yet for this Loop.`
      )}
    </p>
  );
}
