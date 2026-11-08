import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import type { Loop, LoopSummary } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { STAGE_WORDS, loopHref, loopNextAction, tickets } from "./loopNextAction";

/** The line under a finished Loop's name: when it ended. */
function finishedLine(loop: Loop): string {
  if (loop.stage === "cancelled") return `Cancelled ${formatDate(loop.cancelled_at)}`;
  return `Completed ${formatDate(loop.completed_at)}`;
}

/** The quiet facts of a row: Tickets done and warnings. */
function facts(loop: Loop): string[] {
  const shown: string[] = [];
  const { ticket_total: total, ticket_completed: done } = loop.progress;
  if (total > 0) shown.push(`${done} of ${tickets(total)} done`);
  if (loop.warnings.length > 0) {
    shown.push(loop.warnings.length === 1 ? "1 warning" : `${loop.warnings.length} warnings`);
  }
  return shown;
}

function LoopRow({
  loop,
  summary,
  boardId,
  readOnly,
}: {
  loop: Loop;
  summary: LoopSummary | undefined;
  boardId: string;
  readOnly: boolean;
}) {
  const navigate = useNavigate();
  const action = summary ? loopNextAction(summary) : null;
  const finished = loop.stage === "completed" || loop.stage === "cancelled";
  const line = finished ? finishedLine(loop) : action?.waiting;
  const label = readOnly || finished ? null : (action?.label ?? null);
  const shown = facts(loop);
  return (
    <li className="relative flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-[var(--surface-raised)]">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          {/* The name is the row's link; its ::after covers the row, so the whole row opens it. */}
          <Link
            to={loopHref(boardId, loop.id)}
            className="text-[15px] font-semibold text-[var(--foreground)] after:absolute after:inset-0 after:rounded-lg focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-[var(--ring)]"
          >
            {loop.name}
          </Link>
          <span className="font-mono text-xs text-[var(--foreground-faint)]">{loop.key}</span>
          <Chip>{STAGE_WORDS[loop.stage]}</Chip>
        </div>
        {line ? <p className="m-0 mt-1 text-sm text-[var(--muted-foreground)]">{line}</p> : null}
        {shown.length > 0 ? (
          <p className="m-0 mt-0.5 text-xs tabular-nums text-[var(--foreground-faint)]">
            {shown.join(" · ")}
          </p>
        ) : null}
      </div>
      {label && action ? (
        <Button
          size="sm"
          variant="secondary"
          className="relative z-10"
          aria-label={`${label}: ${loop.name}`}
          onClick={() => {
            void navigate(loopHref(boardId, loop.id, action.tab));
          }}
        >
          {label}
        </Button>
      ) : null}
    </li>
  );
}

/**
 * A board's Loops as rows: the name (the row opens the Loop page), the key, the stage, what the
 * Loop waits for and the person's next action as a button, from the board's Loop summaries. A
 * Loop whose summary has not arrived yet shows its row without the line; a read-only board shows
 * no action.
 */
export function LoopList({
  loops,
  summaries,
  boardId,
  readOnly = false,
  framed = true,
  label,
}: {
  loops: Loop[];
  summaries: ReadonlyMap<string, LoopSummary>;
  boardId: string;
  readOnly?: boolean | undefined;
  /** False inside a box of its own (an Expander), so the rows are not boxed twice. */
  framed?: boolean | undefined;
  label: string;
}) {
  return (
    <ul
      aria-label={label}
      className={cn(
        "divide-y divide-[var(--border-soft)] overflow-hidden",
        framed ? "card-surface" : "-mx-3.5 -my-3.5",
      )}
    >
      {loops.map((loop) => (
        <LoopRow
          key={loop.id}
          loop={loop}
          summary={summaries.get(loop.id)}
          boardId={boardId}
          readOnly={readOnly}
        />
      ))}
    </ul>
  );
}
