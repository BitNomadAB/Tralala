import { Fragment, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { renderMarkdown } from "@/lib/markdown";
import type { DocumentKind, LoopDocument } from "@/lib/types";
import { showsAnalysisBrief, type BriefApproval } from "./briefApproval";
import { isHumanBrief } from "./briefs";
import { AnalysisBriefView } from "./BriefView";
import { DOCUMENT_LABELS, isEarlierFormat, staleReasonText, viewAuthorship } from "./loopUi";

/**
 * The current text: the analysis brief's sections, Markdown for everything else. The RoadMap's brief
 * is shown by RoadmapReview, which passes it as `body`.
 */
function CurrentText({
  document,
  technical,
  approval,
}: {
  document: LoopDocument;
  technical: unknown;
  approval?: BriefApproval | undefined;
}) {
  const payload: unknown = document.current_payload;
  if (showsAnalysisBrief(document) && isHumanBrief(payload)) {
    return <AnalysisBriefView brief={payload} technical={technical} approval={approval} />;
  }
  return renderMarkdown(document.current_content ?? "");
}

/** One planning document: its state, current text, approved baseline and revision list. */
export function PlanDocumentPanel({
  kind,
  document,
  technical,
  body,
  approval,
}: {
  kind: DocumentKind;
  document: LoopDocument;
  /** The technical revision's payload, which a brief's "Where does this come from?" reads. */
  technical?: unknown;
  /** The current text as a view of its own (the RoadMap review), instead of the scrolling box. */
  body?: ReactNode;
  /** The approval an analysis brief carries at its end (`BriefApprove`). */
  approval?: BriefApproval | undefined;
}) {
  // Both approvals can supersede the same document, and one sentence says it once.
  const reasons = [...new Set(document.stale_reasons)];
  // A view written for people reads differently from one rendered from the structure.
  const human = kind === "analysis" || kind === "roadmap";
  const authorship = human ? viewAuthorship(document) : null;
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
        {authorship ? <Badge tone="neutral">{authorship}</Badge> : null}
        {human && isEarlierFormat(document) ? <Badge tone="neutral">Earlier format</Badge> : null}
        {document.current_revision_number ? (
          <span className="text-[var(--muted-foreground)]">
            revision {document.current_revision_number}
            {document.approved_revision_number
              ? ` · approved r${document.approved_revision_number}`
              : ""}
          </span>
        ) : null}
      </div>
      {reasons.length > 0 ? (
        <p className="text-[11px] text-[var(--warning)]">
          Needs regeneration:
          {reasons.map((reason) => (
            <Fragment key={reason}>
              {" "}
              <span title={reason}>{staleReasonText(reason)}</span>
            </Fragment>
          ))}
        </p>
      ) : null}
      {document.current_content && body !== undefined ? (
        body
      ) : document.current_content ? (
        <div
          className={
            showsAnalysisBrief(document)
              ? "rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-4 text-sm"
              : "prose-sm max-h-72 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-sm scrollbar-thin"
          }
        >
          <CurrentText document={document} technical={technical} approval={approval} />
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
