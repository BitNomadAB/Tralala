import {
  AlertTriangle,
  Check,
  FileText,
  FolderOpen,
  Loader2,
  MessageSquare,
  Minus,
  Search,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useRef } from "react";
import type { RunStepState } from "@/lib/runPhases";
import { traceStages, type TraceStage } from "@/lib/runTrace";
import type { GenerationRun, RunTraceStep } from "@/lib/types";

const TONE: Record<RunStepState, string> = {
  failed: "text-[var(--destructive)]",
  warning: "text-[var(--warning)]",
  active: "text-[var(--primary)]",
  done: "text-[var(--success)]",
  skipped: "text-[var(--muted-foreground)]",
  pending: "text-[var(--muted-foreground)]",
};

function StageIcon({ state, number }: { state: RunStepState; number: number }) {
  return (
    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-current text-[10px]">
      {state === "done" ? (
        <Check size={10} />
      ) : state === "failed" ? (
        <X size={10} />
      ) : state === "warning" ? (
        <AlertTriangle size={10} />
      ) : state === "skipped" ? (
        <Minus size={10} />
      ) : state === "active" ? (
        <Loader2 size={10} className="animate-spin" />
      ) : (
        number
      )}
    </span>
  );
}

/** The small mark before a step: which tool it called, or what kind of step it is. */
function StepMark({ step }: { step: RunTraceStep }) {
  if (step.kind === "tool") {
    if (step.tool === "search") return <Search size={10} aria-hidden />;
    if (step.tool === "list_files") return <FolderOpen size={10} aria-hidden />;
    return <FileText size={10} aria-hidden />;
  }
  if (step.kind === "note") return <MessageSquare size={10} aria-hidden />;
  if (step.kind === "repair") return <Wrench size={10} aria-hidden />;
  if (step.kind === "limit") return <AlertTriangle size={10} aria-hidden />;
  if (step.kind === "error") return <X size={10} aria-hidden />;
  return <span aria-hidden className="h-1 w-1 rounded-full bg-current" />;
}

const STEP_TONE: Partial<Record<RunTraceStep["kind"], string>> = {
  note: "italic",
  repair: "text-[var(--warning)]",
  limit: "text-[var(--warning)]",
  error: "text-[var(--destructive)]",
};

function StepLine({ step }: { step: RunTraceStep }) {
  return (
    <li className={`flex items-start gap-1.5 ${STEP_TONE[step.kind] ?? ""}`}>
      <span className="mt-[3px] flex h-3 w-3 shrink-0 items-center justify-center">
        <StepMark step={step} />
      </span>
      <span className="break-words">{step.kind === "note" ? `“${step.text}”` : step.text}</span>
    </li>
  );
}

function Stage({ stage, number }: { stage: TraceStage; number: number }) {
  const heading = (
    <span className={`flex items-start gap-2 ${TONE[stage.state]}`}>
      <StageIcon state={stage.state} number={number} />
      <span className="font-medium">{stage.label}</span>
      {stage.steps.length > 3 ? (
        <span className="ml-auto shrink-0 text-[10px] text-[var(--muted-foreground)]">
          {stage.steps.length} steps
        </span>
      ) : null}
    </span>
  );
  if (stage.steps.length === 0) return <li>{heading}</li>;
  return (
    <li>
      {/* Open by default; a person can fold a long stage, and a re-render keeps that choice. */}
      <details open className="group">
        <summary className="cursor-pointer list-none">{heading}</summary>
        <ol className="ml-6 mt-1 flex flex-col gap-1 text-[11px] text-[var(--muted-foreground)]">
          {stage.steps.map((step, index) => (
            <StepLine key={`${step.at}-${index}`} step={step} />
          ))}
        </ol>
      </details>
    </li>
  );
}

/**
 * The run's process tree: every stage it passes through, and under each the steps it took, in plain
 * words — which file the model read, what it searched for, which rule an answer broke, which limit
 * the run reached. It grows while the run works (the run is polled) and stays after it, so a person
 * can read how the answer was made. Compact, it is the stages in a row and the latest step.
 */
export function RunTree({
  purpose,
  run,
  compact,
  failureJson,
}: {
  purpose: "analysis" | "roadmap";
  run: GenerationRun;
  compact: boolean;
  failureJson: string | null;
}) {
  const stages = traceStages(purpose, run);
  const steps = run.trace ?? [];
  const latest = steps.at(-1);
  const list = useRef<HTMLOListElement>(null);
  const running = run.status === "queued" || run.status === "running";

  // While the run works, keep its newest step in view.
  useEffect(() => {
    const element = list.current;
    if (running && element) element.scrollTop = element.scrollHeight;
  }, [running, steps.length]);

  if (compact) {
    return (
      <div className="flex flex-col gap-1 text-[11px]">
        <ol className="flex flex-row flex-wrap gap-2">
          {stages.map((stage, index) => (
            <li key={stage.stage} className={`flex items-center gap-1 ${TONE[stage.state]}`}>
              <StageIcon state={stage.state} number={index + 1} />
              <span className="font-medium">{stage.label}</span>
            </li>
          ))}
        </ol>
        {latest ? <p className="text-[var(--muted-foreground)]">{latest.text}</p> : null}
        {failureJson ? <FailureJson json={failureJson} /> : null}
      </div>
    );
  }
  return (
    <ol
      ref={list}
      className="flex max-h-[70vh] flex-col gap-2 overflow-y-auto pr-1 text-xs scrollbar-thin"
    >
      {stages.map((stage, index) => (
        <Stage key={stage.stage} stage={stage} number={index + 1} />
      ))}
      {failureJson ? (
        <li>
          <FailureJson json={failureJson} />
        </li>
      ) : null}
    </ol>
  );
}

function FailureJson({ json }: { json: string }) {
  return (
    <pre className="overflow-x-auto rounded-md border border-[var(--destructive)] bg-[var(--surface-raised)] p-2 text-[10px] leading-relaxed text-[var(--foreground)] scrollbar-thin">
      {json}
    </pre>
  );
}
