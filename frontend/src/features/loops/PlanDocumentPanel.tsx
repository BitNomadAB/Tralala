import { Badge } from "@/components/ui/badge";
import { renderMarkdown } from "@/lib/markdown";
import type { DocumentKind, LoopDocument } from "@/lib/types";
import { DOCUMENT_LABELS } from "./loopUi";

/** One planning document: its state, current text, approved baseline and revision list. */
export function PlanDocumentPanel({
  kind,
  document,
}: {
  kind: DocumentKind;
  document: LoopDocument;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-[var(--foreground)]">{DOCUMENT_LABELS[kind]}</span>
        <Badge
          tone={
            document.state === "approved"
              ? "success"
              : document.state === "stale"
                ? "warning"
                : "neutral"
          }
        >
          {document.state.replace("_", " ")}
        </Badge>
        {document.current_revision_number ? (
          <span className="text-[var(--muted-foreground)]">
            revision {document.current_revision_number}
            {document.approved_revision_number
              ? ` · approved r${document.approved_revision_number}`
              : ""}
          </span>
        ) : null}
      </div>
      {document.stale_reasons.length > 0 ? (
        <p className="text-[11px] text-[var(--warning)]">
          Needs regeneration: {document.stale_reasons.join(", ")}
        </p>
      ) : null}
      {document.current_content ? (
        <div className="prose-sm max-h-72 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm scrollbar-thin">
          {renderMarkdown(document.current_content)}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
          Nothing here yet.
        </p>
      )}
      {document.current_content &&
      document.approved_content &&
      document.approved_revision_number !== document.current_revision_number ? (
        <details className="text-xs text-[var(--muted-foreground)]">
          <summary>Show the approved baseline (r{document.approved_revision_number})</summary>
          <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-[var(--border)] p-2 scrollbar-thin">
            {renderMarkdown(document.approved_content)}
          </div>
        </details>
      ) : null}
      {document.revisions.length > 0 ? (
        <details className="text-xs text-[var(--muted-foreground)]">
          <summary>{document.revisions.length} revision(s)</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {document.revisions.map((revision) => (
              <li key={revision.id}>
                r{revision.revision_number} · {revision.status} · {revision.author_name} ·{" "}
                {new Date(revision.created_at).toLocaleString()}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
