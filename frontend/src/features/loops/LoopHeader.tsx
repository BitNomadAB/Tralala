import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, FileText, ListChecks, Sparkles } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { keys, useLoopDocuments, useReadiness } from "@/lib/queries";
import { useAuth } from "@/features/auth/AuthProvider";
import { renderMarkdown } from "@/lib/markdown";
import type { Card, DocumentKind, Loop } from "@/lib/types";
import { LoopCompletionDialog } from "./LoopCompletionDialog";
import { LoopPlanDialog } from "./LoopPlanDialog";

const STAGE_TONES: Record<Loop["stage"], BadgeTone> = {
  draft: "neutral",
  analysis_review: "brand",
  planning: "brand",
  roadmap_review: "brand",
  ready: "success",
  in_progress: "brand",
  replanning: "warning",
  awaiting_qa: "warning",
  completed: "success",
  cancelled: "neutral",
};

const DOCUMENT_LABELS: Record<DocumentKind, string> = {
  info: "Info",
  analysis_ai: "Analysis (AI)",
  analysis: "Analysis",
  roadmap_ai: "RoadMap (AI)",
  roadmap: "RoadMap",
};

type Tab = "info" | "analysis" | "roadmap";

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
  const [tab, setTab] = useState<Tab | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [completionOpen, setCompletionOpen] = useState(false);
  const documents = useLoopDocuments(boardId, loop.id);
  const readiness = useReadiness(boardId, loop.id);
  const { actor } = useAuth();
  const isHuman = actor?.type === "user";
  const readOnly = boardStatus !== "active" || loop.stage === "completed" || loop.stage === "cancelled";

  const humanActions = useMemo(
    () =>
      (readiness.data?.items ?? []).filter(
        (item) => item.human_action_required && item.ready,
      ),
    [readiness.data],
  );

  const documentState = (kind: DocumentKind) => documents.data?.documents[kind]?.state ?? "empty";

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

      {loop.goal ? (
        <p className="text-xs text-[var(--muted-foreground)]">{loop.goal}</p>
      ) : null}

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

function LoopDocumentDialog({
  boardId,
  loop,
  initialTab,
  isHuman,
  readOnly,
  onClose,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  initialTab: Tab;
  isHuman: boolean;
  readOnly: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [technical, setTechnical] = useState(false);
  const [infoDraft, setInfoDraft] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();
  const documentsQuery = useLoopDocuments(boardId, loop.id);
  const documents = documentsQuery.data?.documents;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: keys.loopDocuments(boardId, loop.id) });
    onChanged();
  };

  const errorText = (error: unknown) =>
    error instanceof ApiError ? error.message : "Please try again.";

  const saveInfo = useMutation({
    mutationFn: () =>
      api.saveInfo(boardId, loop.id, {
        content: infoDraft ?? "",
        expected_revision_id: documents?.info.current_revision_id ?? null,
      }),
    onSuccess: () => {
      setInfoDraft(null);
      invalidate();
      toast.push({ title: "Info saved as a new revision", variant: "success" });
    },
    onError: (error) => toast.push({ title: "Could not save Info", description: errorText(error), variant: "error" }),
  });

  const generate = useMutation({
    mutationFn: (purpose: "analysis" | "roadmap") =>
      api.startGeneration(boardId, loop.id, purpose),
    onSuccess: (run) => {
      invalidate();
      toast.push({
        title: "Generation started",
        description: `Run ${run.status}. Refresh to follow its progress.`,
        variant: "success",
      });
    },
    onError: (error) =>
      toast.push({ title: "Generation unavailable", description: errorText(error), variant: "error" }),
  });

  const review = useMutation({
    mutationFn: (args: { scope: "analysis" | "roadmap"; decision: "approved" | "changes_requested" }) => {
      const revisions: Record<string, string> = {};
      const kinds =
        args.scope === "analysis"
          ? (["info", "analysis_ai", "analysis"] as DocumentKind[])
          : (["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"] as DocumentKind[]);
      kinds.forEach((kind) => {
        const revision = documents?.[kind]?.current_revision_id;
        if (revision) revisions[kind] = revision;
      });
      const payload = {
        decision: args.decision,
        version: loop.version,
        revisions,
        feedback,
      };
      return args.scope === "analysis"
        ? api.reviewAnalysis(boardId, loop.id, payload)
        : api.reviewRoadmap(boardId, loop.id, payload);
    },
    onSuccess: () => {
      setFeedback("");
      invalidate();
      toast.push({ title: "Decision recorded", variant: "success" });
    },
    onError: (error) =>
      toast.push({ title: "Could not record the decision", description: errorText(error), variant: "error" }),
  });

  const visible = useMemo(() => {
    if (tab === "info") return ["info"] as DocumentKind[];
    if (tab === "analysis") return [technical ? "analysis_ai" : "analysis"] as DocumentKind[];
    return [technical ? "roadmap_ai" : "roadmap"] as DocumentKind[];
  }, [tab, technical]);

  const scopeDocuments = tab === "analysis" ? ["analysis_ai", "analysis"] : ["roadmap_ai", "roadmap"];
  const canReviewScope = isHuman && scopeDocuments.every((kind) => {
    const document = documents?.[kind as DocumentKind];
    return document?.current_revision_id && document.state !== "stale";
  });
  const approvedForScope =
    tab === "analysis"
      ? documents?.analysis.state === "approved"
      : documents?.roadmap.state === "approved";

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={`${loop.key} planning documents`}
        description="Info is written by a person. Analysis and RoadMap pair a technical view with a plain-language one."
        className="w-[min(960px,96vw)]"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] pb-2">
          {(["info", "analysis", "roadmap"] as Tab[]).map((entry) => (
            <Button
              key={entry}
              size="sm"
              variant={tab === entry ? "primary" : "ghost"}
              onClick={() => setTab(entry)}
            >
              {entry === "info" ? "Info" : entry === "analysis" ? "Analysis" : "RoadMap"}
            </Button>
          ))}
          {tab !== "info" ? (
            <Button size="sm" variant="ghost" onClick={() => setTechnical((value) => !value)}>
              {technical ? "Human view" : "Technical view"}
            </Button>
          ) : null}
          {tab !== "info" ? (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto"
              disabled={readOnly || generate.isPending}
              onClick={() => generate.mutate(tab)}
            >
              <Sparkles size={14} /> Generate {tab === "analysis" ? "analysis" : "RoadMap"}
            </Button>
          ) : null}
        </div>

        <div className="mt-3 flex flex-col gap-4">
          {visible.map((kind) => {
            const document = documents?.[kind];
            if (!document) return null;
            return (
              <section key={kind} className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium text-[var(--foreground)]">
                    {DOCUMENT_LABELS[kind]}
                  </span>
                  <Badge tone={document.state === "approved" ? "success" : document.state === "stale" ? "warning" : "neutral"}>
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
          })}

          {tab === "info" ? (
            <div className="flex flex-col gap-2">
              <Field label="Write or revise Info" htmlFor="loop-info">
                <Textarea
                  id="loop-info"
                  rows={8}
                  value={infoDraft ?? documents?.info.current_content ?? ""}
                  onChange={(event) => setInfoDraft(event.target.value)}
                  placeholder="Requirements, constraints, links and desired outcomes. Only a person can edit this."
                  maxLength={200000}
                  disabled={readOnly || !isHuman}
                />
              </Field>
              {!isHuman ? (
                <p className="text-[11px] text-[var(--warning)]">
                  Agents cannot write Info; ask a person to record it.
                </p>
              ) : null}
              <div className="flex justify-end">
                <Button
                  disabled={readOnly || !isHuman || saveInfo.isPending || infoDraft === null}
                  onClick={() => saveInfo.mutate()}
                >
                  Save as new revision
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
              {!isHuman ? (
                <p className="text-[11px] text-[var(--warning)]">
                  Approving is a human decision; agents can generate and comment only.
                </p>
              ) : null}
              <Field label="Feedback (optional)" htmlFor="loop-review-feedback">
                <Input
                  id="loop-review-feedback"
                  value={feedback}
                  onChange={(event) => setFeedback(event.target.value)}
                  maxLength={20000}
                  disabled={readOnly || !isHuman}
                />
              </Field>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  variant="outline"
                  disabled={readOnly || !isHuman || review.isPending}
                  onClick={() =>
                    review.mutate({
                      scope: tab === "analysis" ? "analysis" : "roadmap",
                      decision: "changes_requested",
                    })
                  }
                >
                  Request changes
                </Button>
                <Button
                  disabled={readOnly || !canReviewScope || review.isPending || approvedForScope}
                  onClick={() =>
                    review.mutate({
                      scope: tab === "analysis" ? "analysis" : "roadmap",
                      decision: "approved",
                    })
                  }
                >
                  {approvedForScope ? "Approved" : `Approve ${tab === "analysis" ? "analysis" : "RoadMap"}`}
                </Button>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function blockerLabel(blocker: {
  type: string;
  key?: string | null;
  title?: string;
  name?: string;
  reason: string;
  phase_number?: number | null;
}): string {
  if (blocker.type === "phase") {
    return `Phase ${blocker.phase_number ?? "?"} ${blocker.name ?? ""}`.trim();
  }
  return `${blocker.key ?? "Ticket"} ${blocker.title ?? ""}`.trim();
}

export type { Card };
