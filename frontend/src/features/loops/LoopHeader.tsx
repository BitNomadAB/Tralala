import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import { useReadiness } from "@/lib/queries";
import type { Board, Loop, LoopSummary } from "@/lib/types";
import { decisionShown, loopDecision } from "./loopDecision";
import { LoopDialogs, type LoopDialog } from "./LoopDialogs";
import { loopNextAction, STAGE_WORDS } from "./loopNextAction";
import type { LoopView } from "./useLoopView";

/**
 * The Loop's header: its name as the page title, the key and the stage under it, what the Loop
 * waits for (from the board's Loop summaries) and the one primary button for the person's next
 * decision. Everything else is in the quiet "Loop actions" menu.
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
  const [dialog, setDialog] = useState<LoopDialog | null>(null);
  const readiness = useReadiness(board.id, loop.id);
  const { actor } = useAuth();
  const next = summary ? loopNextAction(summary) : null;
  const decision = decisionShown(loopDecision(next), view);

  const humanActions = useMemo(
    () => (readiness.data?.items ?? []).filter((item) => item.human_action_required && item.ready),
    [readiness.data],
  );

  const locked = readOnly ? "The Loop is read-only" : undefined;
  const items: MenuItem[] = [
    { label: "Edit Loop", disabled: readOnly, hint: locked, onSelect: () => setDialog("edit") },
    { label: "Loop agents", onSelect: () => setDialog("agents") },
    ...(decision?.kind === "finalize"
      ? []
      : [
          {
            label: "Finalize Loop",
            disabled: readOnly,
            hint: locked,
            onSelect: () => {
              setDialog("completion");
            },
          },
        ]),
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
          <h1 className="truncate text-[22px] font-semibold leading-tight">{loop.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Chip mono>{loop.key}</Chip>
            <Chip>{STAGE_WORDS[loop.stage]}</Chip>
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
        <ul className="flex flex-wrap gap-2 text-[11px]">
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
        <ul className="flex flex-col gap-1 text-[11px] text-[var(--warning)]">
          {humanActions.map((item) => (
            <li key={item.id} className="inline-flex items-center gap-1">
              <AlertTriangle size={12} aria-hidden="true" />
              <span>
                <strong>{item.key}</strong> {item.title} — human action required.
                {item.downstream_phase_numbers.length > 0
                  ? ` Phases ${item.downstream_phase_numbers.join(", ")} cannot start until a human
                     confirms this.`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      <LoopDialogs
        open={dialog}
        onClose={() => setDialog(null)}
        board={board}
        loop={loop}
        isHuman={actor?.type === "user"}
        columnCount={columnCount}
        onChanged={onChanged}
      />
    </header>
  );
}
