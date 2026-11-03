import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import type { DocumentKind, Loop, LoopDocuments } from "@/lib/types";
import { errorText, type PlanScope } from "./loopUi";

/**
 * The human side of the planning documents: the Info draft, the review feedback, the reset
 * confirmation and the three mutations that record them.
 */
export function usePlanReview({
  boardId,
  loop,
  documents,
  invalidate,
}: {
  boardId: string;
  loop: Loop;
  documents: LoopDocuments["documents"] | undefined;
  invalidate: () => void;
}) {
  const toast = useToast();
  const [infoDraft, setInfoDraft] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);

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
    onError: (error) => {
      toast.push({ title: "Could not save Info", description: errorText(error), variant: "error" });
    },
  });

  const review = useMutation({
    mutationFn: (args: { scope: PlanScope; decision: "approved" | "changes_requested" }) => {
      const revisions: Record<string, string> = {};
      const kinds =
        args.scope === "analysis"
          ? (["info", "analysis_ai", "analysis"] as DocumentKind[])
          : (["info", "analysis_ai", "analysis", "roadmap_ai", "roadmap"] as DocumentKind[]);
      kinds.forEach((kind) => {
        const revision = documents?.[kind].current_revision_id;
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
    onError: (error) => {
      toast.push({
        title: "Could not record the decision",
        description: errorText(error),
        variant: "error",
      });
    },
  });

  const resetScope = useMutation({
    mutationFn: (scope: PlanScope) =>
      api.resetScope(boardId, loop.id, scope, { version: loop.version }),
    onSuccess: () => {
      setConfirmWithdraw(false);
      setFeedback("");
      invalidate();
      toast.push({
        title: "Scope reset",
        description: "The document is cleared, so it has to be generated again.",
        variant: "success",
      });
    },
    onError: (error) => {
      toast.push({
        title: "Could not reset the scope",
        description: errorText(error),
        variant: "error",
      });
    },
  });

  return {
    infoDraft,
    setInfoDraft,
    feedback,
    setFeedback,
    confirmWithdraw,
    setConfirmWithdraw,
    saveInfo,
    review,
    resetScope,
  };
}
