import { AlertTriangle, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import type { Loop } from "@/lib/types";
import { STAGE_TONES } from "./loopUi";

export function LoopList({
  loops,
  boardId,
  empty,
}: {
  loops: Loop[];
  boardId: string;
  empty: string;
}) {
  if (loops.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-[var(--border)] p-4 text-xs text-[var(--muted-foreground)]">
        {empty}
      </p>
    );
  }
  return (
    <ul className="grid gap-2 md:grid-cols-2">
      {loops.map((loop) => (
        <li key={loop.id}>
          <Link
            to={`/boards/${boardId}/loops/${loop.id}`}
            className="card-surface flex h-full flex-col gap-2 p-3 transition hover:border-[var(--primary)]"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
                {loop.key}
              </span>
              <span className="text-sm font-medium">{loop.name}</span>
              <Badge tone={STAGE_TONES[loop.stage]}>{loop.stage.replace("_", " ")}</Badge>
              <ArrowRight size={14} className="ml-auto text-[var(--muted-foreground)]" />
            </div>
            {loop.goal ? (
              <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">{loop.goal}</p>
            ) : null}
            <div className="mt-auto flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
              <span>
                {loop.progress.ticket_completed}/{loop.progress.ticket_total} tickets
              </span>
              {loop.plan ? <span>· {loop.plan.phase_count} phases</span> : null}
              {loop.qa ? (
                <span>
                  · QA {loop.qa.status.replace("_", " ")}
                  {loop.qa.open ? " (open)" : ""}
                </span>
              ) : null}
              {loop.warnings.length > 0 ? (
                <Badge tone="warning">
                  <AlertTriangle size={11} /> {loop.warnings.length}
                </Badge>
              ) : null}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
