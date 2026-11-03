import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { generationAgents } from "@/lib/boardAgents";
import { keys, useAgents, useBoard, useLoopAgents, useLoopDocuments } from "@/lib/queries";
import type { DocumentKind, Loop } from "@/lib/types";
import { GenerationRunAside, GenerationRunPanel, LastRunStatus } from "./GenerationRunPanel";
import { InfoEditor } from "./InfoEditor";
import { LoopPlanTabs } from "./LoopPlanTabs";
import type { PlanScope, PlanTab } from "./loopUi";
import { PlanDocumentPanel } from "./PlanDocumentPanel";
import { ScopeReview } from "./ScopeReview";
import { useGenerationRun } from "./useGenerationRun";
import { usePlanReview } from "./usePlanReview";

export function LoopDocumentDialog({
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
  initialTab: PlanTab;
  isHuman: boolean;
  readOnly: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<PlanTab>(initialTab);
  const [technical, setTechnical] = useState(false);
  const [agentId, setAgentId] = useState("");
  const queryClient = useQueryClient();
  const documentsQuery = useLoopDocuments(boardId, loop.id);
  const documents = documentsQuery.data?.documents;
  const boardQuery = useBoard(boardId);
  const agentsQuery = useAgents();
  const candidates = useMemo(
    () => generationAgents(agentsQuery.data ?? [], boardQuery.data?.agent_ids),
    [agentsQuery.data, boardQuery.data?.agent_ids],
  );
  const preferencesQuery = useLoopAgents(boardId, loop.id);
  const savedAgentId =
    tab === "analysis"
      ? preferencesQuery.data?.analysis_agent_id
      : tab === "roadmap"
        ? preferencesQuery.data?.roadmap_agent_id
        : null;
  const savedAgentName = candidates.agents.find((agent) => agent.id === savedAgentId)?.name;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: keys.loopDocuments(boardId, loop.id) });
    void queryClient.invalidateQueries({ queryKey: keys.generationRuns(boardId, loop.id) });
    onChanged();
  };

  const planReview = usePlanReview({ boardId, loop, documents, invalidate });
  const { setConfirmWithdraw } = planReview;
  const generation = useGenerationRun({
    boardId,
    loopId: loop.id,
    tab,
    agentId,
    invalidate,
    onStarted: () => setConfirmWithdraw(false),
  });

  const visible = useMemo(() => {
    if (tab === "info") return ["info"] as DocumentKind[];
    if (tab === "analysis") return [technical ? "analysis_ai" : "analysis"] as DocumentKind[];
    return [technical ? "roadmap_ai" : "roadmap"] as DocumentKind[];
  }, [tab, technical]);

  const scopeDocuments =
    tab === "analysis" ? ["analysis_ai", "analysis"] : ["roadmap_ai", "roadmap"];
  const scopeHasText = scopeDocuments.some((kind) =>
    Boolean(documents?.[kind as DocumentKind]?.current_content?.trim()),
  );
  const approvedForScope =
    tab === "analysis"
      ? documents?.analysis.state === "approved"
      : documents?.roadmap.state === "approved";
  // Reset is for the draft too, not only for an approval: a bad generation has to be clearable before
  // anyone signs it off.
  const canResetScope = isHuman && !readOnly && (scopeHasText || approvedForScope);
  const canReviewScope =
    isHuman &&
    scopeHasText &&
    scopeDocuments.every((kind) => {
      const document = documents?.[kind as DocumentKind];
      return document?.current_revision_id && document.state !== "stale";
    });
  const scope: PlanScope = tab === "analysis" ? "analysis" : "roadmap";
  const scopeLabel = tab === "analysis" ? "analysis" : "RoadMap";
  const { generating, visibleRun } = generation;
  const dismissRun = generating ? undefined : generation.dismissFailure;

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={`${loop.key} planning documents`}
        description="Info is written by a person. Analysis and RoadMap pair a technical view with a plain-language one."
        className="w-[min(960px,96vw)]"
      >
        {visibleRun ? (
          <GenerationRunPanel scope={scope} run={visibleRun} onDismiss={dismissRun} />
        ) : null}
        <LoopPlanTabs
          tab={tab}
          onTabChange={(entry) => {
            // A pending reset confirmation belongs to the tab it was asked on.
            if (entry !== tab) setConfirmWithdraw(false);
            setTab(entry);
          }}
          technical={technical}
          onToggleTechnical={() => setTechnical((value) => !value)}
          agentId={agentId}
          onAgentChange={setAgentId}
          candidates={candidates}
          savedAgentName={savedAgentName}
          agentLocked={readOnly || generation.following}
          generating={generating}
          generateDisabled={readOnly || generation.generate.isPending || generating}
          onGenerate={(purpose) => generation.generate.mutate(purpose)}
        />
        {visibleRun ? (
          <GenerationRunPanel scope={scope} run={visibleRun} onDismiss={dismissRun} />
        ) : null}
        {tab !== "info" ? (
          <LastRunStatus
            scope={tab}
            lastRun={generation.lastRun}
            loading={generation.lastRunLoading}
          />
        ) : null}

        <div className="mt-3 flex flex-col gap-4">
          {visible.map((kind) => {
            const document = documents?.[kind];
            if (!document) return null;
            return <PlanDocumentPanel key={kind} kind={kind} document={document} />;
          })}

          {tab === "info" ? (
            <InfoEditor
              value={planReview.infoDraft ?? documents?.info.current_content ?? ""}
              onChange={planReview.setInfoDraft}
              isHuman={isHuman}
              readOnly={readOnly}
              canSave={
                !readOnly &&
                isHuman &&
                !planReview.saveInfo.isPending &&
                planReview.infoDraft !== null
              }
              onSave={() => planReview.saveInfo.mutate()}
            />
          ) : (
            <ScopeReview
              scopeLabel={scopeLabel}
              isHuman={isHuman}
              readOnly={readOnly}
              feedback={planReview.feedback}
              onFeedbackChange={planReview.setFeedback}
              canReset={canResetScope}
              confirmReset={planReview.confirmWithdraw}
              onConfirmResetChange={setConfirmWithdraw}
              resetPending={planReview.resetScope.isPending}
              onReset={() => planReview.resetScope.mutate(scope)}
              canReview={canReviewScope}
              approved={approvedForScope}
              reviewPending={planReview.review.isPending}
              onDecision={(decision) => planReview.review.mutate({ scope, decision })}
            />
          )}
        </div>
      </DialogContent>
      {visibleRun ? (
        <GenerationRunAside scope={scope} run={visibleRun} onDismiss={dismissRun} />
      ) : null}
    </Dialog>
  );
}
