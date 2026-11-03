import { AlertTriangle, Bot, ClipboardCheck, FileText, ListChecks } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/useAuth";
import { useLoopDocuments, useReadiness } from "@/lib/queries";
import type { DocumentKind, Loop } from "@/lib/types";
import { LoopAgentsDialog } from "./LoopAgentsDialog";
import { LoopCompletionDialog } from "./LoopCompletionDialog";
import { LoopDocumentDialog } from "./LoopDocumentDialog";
import { LoopPlanDialog } from "./LoopPlanDialog";
import { STAGE_TONES, type PlanTab } from "./loopUi";

export function LoopHeader({
  boardId,
  loop,
  boardStatus,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  boardStatus: string;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<PlanTab | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const [completionOpen, setCompletionOpen] = useState(false);
  const documents = useLoopDocuments(boardId, loop.id);
  const readiness = useReadiness(boardId, loop.id);
  const { actor } = useAuth();
  const isHuman = actor?.type === "user";
  const readOnly =
    boardStatus !== "active" || loop.stage === "completed" || loop.stage === "cancelled";

  const humanActions = useMemo(
    () => (readiness.data?.items ?? []).filter((item) => item.human_action_required && item.ready),
    [readiness.data],
  );

  const documentState = (kind: DocumentKind) => documents.data?.documents[kind].state ?? "empty";

  return (
    <header className="flex flex-col gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral" className="font-mono">
          {loop.key}
        </Badge>
        <h1 className="truncate text-lg font-semibold">{loop.name}</h1>
        <Badge tone={STAGE_TONES[loop.stage]}>{loop.stage.replace("_", " ")}</Badge>
        <span className="text-xs text-[var(--muted-foreground)]">
          {loop.progress.ticket_completed}/{loop.progress.ticket_total} tickets done
          {loop.plan ? ` · ${loop.plan.phase_count} phases` : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => setTab("info")}>
            <FileText size={14} /> Info
            <DocumentDot state={documentState("info")} />
          </Button>
          <Button size="sm" variant="outline" onClick={() => setTab("analysis")}>
            Analysis
            <DocumentDot state={documentState("analysis")} />
          </Button>
          <Button size="sm" variant="outline" onClick={() => setTab("roadmap")}>
            RoadMap
            <DocumentDot state={documentState("roadmap")} />
          </Button>
          <Button size="sm" variant="outline" onClick={() => setAgentsOpen(true)}>
            <Bot size={14} /> Loop agents
          </Button>
          <Button size="sm" variant="outline" onClick={() => setPlanOpen(true)}>
            <ListChecks size={14} /> Plan &amp; readiness
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={readOnly}
            onClick={() => setCompletionOpen(true)}
          >
            <ClipboardCheck size={14} /> Complete &amp; QA
          </Button>
        </div>
      </div>

      {loop.goal ? <p className="text-xs text-[var(--muted-foreground)]">{loop.goal}</p> : null}

      {loop.warnings.length > 0 ? (
        <ul className="flex flex-wrap gap-2 text-[11px]">
          {loop.warnings.map((warning) => (
            <li key={`${warning.code}-${warning.kind ?? ""}`}>
              <Badge tone={warning.code === "approval_required" ? "neutral" : "warning"}>
                <AlertTriangle size={11} /> {warning.message}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {humanActions.length > 0 ? (
        <ul className="flex flex-col gap-1 text-[11px] text-[var(--warning)]">
          {humanActions.map((item) => (
            <li key={item.id} className="inline-flex items-center gap-1">
              <AlertTriangle size={12} />
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

      {tab ? (
        <LoopDocumentDialog
          boardId={boardId}
          loop={loop}
          initialTab={tab}
          isHuman={isHuman}
          readOnly={readOnly}
          onClose={() => setTab(null)}
          onChanged={onChanged}
        />
      ) : null}

      <LoopAgentsDialog
        boardId={boardId}
        loop={loop}
        open={agentsOpen}
        onClose={() => setAgentsOpen(false)}
      />

      <LoopPlanDialog
        boardId={boardId}
        loop={loop}
        open={planOpen}
        onClose={() => setPlanOpen(false)}
        onChanged={onChanged}
      />

      <LoopCompletionDialog
        boardId={boardId}
        loop={loop}
        open={completionOpen}
        isHuman={isHuman}
        onClose={() => setCompletionOpen(false)}
        onChanged={onChanged}
      />
    </header>
  );
}

function DocumentDot({ state }: { state: string }) {
  const toneClass =
    state === "approved"
      ? "text-[var(--success)]"
      : state === "stale"
        ? "text-[var(--warning)]"
        : state === "empty"
          ? "text-[var(--border)]"
          : "text-[var(--primary)]";
  return (
    <span
      className={`ml-1 inline-block h-1.5 w-1.5 rounded-full bg-current ${toneClass}`}
      title={state.replace("_", " ")}
      aria-label={state}
    />
  );
}
