import { createPortal } from "react-dom";
import { describeRunCost, describeRunRepositories } from "@/lib/loopRuns";
import type { GenerationRun } from "@/lib/types";
import type { PlanScope } from "./loopUi";
import { RunPhases } from "./RunPhases";

interface RunPanelProps {
  scope: PlanScope;
  run: GenerationRun;
  onDismiss: (() => void) | undefined;
}

/** The run's steps inside the dialog, on screens too narrow for the panel beside it. */
export function GenerationRunPanel({ scope, run, onDismiss }: RunPanelProps) {
  return (
    <div className="mt-2 2xl:hidden">
      <RunPhases purpose={scope} run={run} compact onDismiss={onDismiss} />
    </div>
  );
}

/** The run's steps beside the dialog on a wide screen. */
export function GenerationRunAside({ scope, run, onDismiss }: RunPanelProps) {
  return createPortal(
    // Outside the dialog content on purpose: that element scrolls, so a panel positioned
    // beside it would be clipped. This one sits at the right edge of the window instead, and
    // it takes pointer events because a modal dialog sets `pointer-events: none` on the body.
    <aside className="pointer-events-auto fixed right-6 top-1/2 z-50 hidden w-60 -translate-y-1/2 2xl:block">
      <RunPhases purpose={scope} run={run} onDismiss={onDismiss} />
    </aside>,
    document.body,
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
