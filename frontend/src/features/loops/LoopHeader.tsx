import { AlertTriangle } from "lucide-react";
import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import { useReadiness } from "@/lib/queries";
import type { Board, Loop, LoopSummary } from "@/lib/types";
import {
  completionMenuItems,
  completionOffered,
  decisionShown,
  loopDecision,
} from "./loopDecision";
import { LoopDialogs } from "./LoopDialogs";
import { loopNextAction, STAGE_WORDS } from "./loopNextAction";
import { useLoopDialog } from "./useLoopDialog";
import type { LoopView } from "./useLoopView";
import { WithoutPlanChip } from "./WithoutPlanChip";

/**
 * What a person's task not confirmed yet means for the Phases after it: their work goes on, and a
 * Ticket done there stays awaiting confirmation until the person confirms the task.
 */
function dependentPhasesText(phases: readonly number[]): string {
  return `Phases ${phases.join(", ")} depend on it: their work need not wait for it, and stays awaiting confirmation until a person confirms this.`;
}

/**
 * The Loop's header: its name as the page title, the key and the stage under it (with "Without a
 * plan" for a Loop that runs without one), what the Loop waits for (from the board's Loop
 * summaries) and the one primary button for the person's next decision. Everything else is in the
 * quiet "Loop actions" menu.
 */
export function LoopHeader({
  board,
  loop,
  summary,
  view,
  readOnly,
  columnCount,
  onChanged,
  onToggleActivity,
}: {
  board: Board;
  loop: Loop;
  /** This Loop's row of `GET /boards/{id}/loop-summaries`; undefined until it arrives. */
  summary: LoopSummary | undefined;
  view: LoopView;
  readOnly: boolean;
  columnCount: number;
  onChanged: () => void;
  onToggleActivity: () => void;
}) {
  const locked = readOnly ? "The Loop is read-only" : undefined;
  // `?dialog=completion` opens the completion dialog when the Loop offers it.
  const {
    open: dialog,
    setOpen: setDialog,
    close: closeDialog,
  } = useLoopDialog(view, completionOffered(loop, locked));
  const readiness = useReadiness(board.id, loop.id);
  const { actor } = useAuth();
  const next = summary ? loopNextAction(summary) : null;
  const decision = decisionShown(loopDecision(next), view);

  const humanActions = useMemo(
    () =>
      (readiness.data?.items ?? []).filter(
        (item) => item.human_action_required && (item.ready || item.awaiting_confirmation),
      ),
    [readiness.data],
  );

  const items: MenuItem[] = [
    { label: "Edit Loop", disabled: readOnly, hint: locked, onSelect: () => setDialog("edit") },
    { label: "Loop agents", onSelect: () => setDialog("agents") },
    ...completionMenuItems(loop, decision, locked, () => setDialog("completion")),
    {
      label: "Save columns as template",
      disabled: readOnly,
      hint: locked,
      onSelect: () => setDialog("template"),
    },
    { label: "Board activity", onSelect: onToggleActivity },
    { label: "Export board", onSelect: () => window.location.assign(api.exportUrl(board.id)) },
    {
      label: "Cancel Loop",
      danger: true,
      disabled: readOnly,
      hint: locked,
      onSelect: () => setDialog("cancel"),
    },
  ];

  return (
    <header className="flex flex-col gap-2">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          {/* A long name wraps instead of being cut off (WCAG 1.4.10). */}
          <h1 className="break-words text-[22px] font-semibold leading-tight">{loop.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Chip mono>{loop.key}</Chip>
            <Chip>{STAGE_WORDS[loop.stage]}</Chip>
            {loop.without_plan ? <WithoutPlanChip /> : null}
            <span className="tabular-nums">
              {loop.progress.ticket_completed}/{loop.progress.ticket_total} Tickets done
              {loop.plan ? ` · ${loop.plan.phase_count} phases` : ""}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {decision ? (
            <Button
              onClick={() =>
                decision.kind === "review"
                  ? view.show("plan", decision.doc)
                  : setDialog("completion")
              }
            >
              {decision.label}
            </Button>
          ) : null}
          <Menu label="Loop actions" items={items} />
        </div>
      </div>

      {next ? <p className="text-sm text-[var(--foreground)]">{next.waiting}</p> : null}

      {loop.goal ? <p className="text-xs text-[var(--muted-foreground)]">{loop.goal}</p> : null}

      {loop.warnings.length > 0 ? (
        <ul className="flex flex-wrap gap-2 text-xs">
          {loop.warnings.map((warning) => (
            <li key={`${warning.code}-${warning.kind ?? ""}`}>
              <Badge tone={warning.code === "approval_required" ? "neutral" : "warning"}>
                <AlertTriangle size={11} aria-hidden="true" /> {warning.message}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {humanActions.length > 0 ? (
        <ul className="flex flex-col gap-1 text-xs text-[var(--warning)]">
          {humanActions.map((item) => (
            <li key={item.id} className="inline-flex items-center gap-1">
              <AlertTriangle size={12} aria-hidden="true" />
              <span>
                <strong>{item.key}</strong> {item.title} — human action required.
                {item.downstream_phase_numbers.length > 0
                  ? ` ${dependentPhasesText(item.downstream_phase_numbers)}`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <LoopDialogs
        open={dialog}
        onClose={closeDialog}
        board={board}
        loop={loop}
        isHuman={actor?.type === "user"}
        columnCount={columnCount}
        onChanged={onChanged}
        openDecisions={summary?.poc_decisions.open ?? 0}
      />
    </header>
  );
}
