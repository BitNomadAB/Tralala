import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { candidateMarkdown, staleCandidate } from "@/lib/keptCandidate";
import { renderMarkdown } from "@/lib/markdown";
import type { GenerationRun } from "@/lib/types";

/**
 * The answer of the scope's last run when it arrived after the documents it read had changed.
 *
 * The server keeps that answer on the run instead of promoting it, and until now no screen showed it:
 * the person saw a failed run and nothing of the minutes it had cost. It is rendered the way the
 * technical view renders a generated draft, labelled as not promoted, with a new run one click away.
 */
export function KeptCandidate({
  run,
  scopeLabel,
  regenerateDisabled,
  onRegenerate,
}: {
  run: GenerationRun | undefined;
  scopeLabel: string;
  regenerateDisabled: boolean;
  onRegenerate: () => void;
}) {
  const candidate = staleCandidate(run);
  if (!candidate) return null;
  return (
    <section
      aria-label={`Kept ${scopeLabel} result`}
      className="mt-3 flex flex-col gap-2 rounded-lg border border-dashed border-[var(--warning)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-[var(--foreground)]">Kept result</span>
        <Badge tone="warning">not promoted</Badge>
      </div>
      <p className="text-[11px] text-[var(--muted-foreground)]">
        The planning documents changed while the model was working, so this {scopeLabel} was kept
        for inspection and not used. It was written from the documents as they were when the run
        started.
      </p>
      <div className="prose-sm max-h-72 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm scrollbar-thin">
        {renderMarkdown(candidateMarkdown(candidate))}
      </div>
      <div className="flex justify-end">
        <Button size="sm" variant="outline" disabled={regenerateDisabled} onClick={onRegenerate}>
          Regenerate from the current Info
        </Button>
      </div>
    </section>
  );
}
