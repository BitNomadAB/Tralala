import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { generationAgents } from "@/lib/boardAgents";
import { keys, useAgents, useBoard, useLoopAgents, useLoopDocuments } from "@/lib/queries";
import type { DocumentKind, Loop } from "@/lib/types";
import { showsAnalysisBrief } from "./briefApproval";
import { GenerationRunAside, GenerationRunPanel, LastRunStatus } from "./GenerationRunPanel";
import { InfoEditor } from "./InfoEditor";
import { InfoSaveGuard } from "./InfoSaveGuard";
import { KeptCandidate } from "./KeptCandidate";
import { LoopPlanTabs } from "./LoopPlanTabs";
import { FOR_PEOPLE_PURPOSE, rewriteBlockedReason, type PlanScope, type PlanTab } from "./loopUi";
import { PlanDocumentPanel } from "./PlanDocumentPanel";
import { approvalLine, approveRoadmapLabel, reviewPlan, ticketCount } from "./roadmapPlan";
import { RoadmapReview } from "./RoadmapReview";
import { ScopeReview } from "./ScopeReview";
import { useGenerationRun } from "./useGenerationRun";
import { usePlanReview } from "./usePlanReview";

/**
 * The Loop's planning documents on the Plan tab: Info, Analysis and RoadMap with their generation
 * controls, the run's progress, the kept candidate and the person's review. `tab` is the open
 * document, which the page keeps in the URL (`?doc=`).
 */
export function LoopDocumentsPanel({
  boardId,
  loop,
  tab,
  onTabChange,
  isHuman,
  readOnly,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  tab: PlanTab;
  onTabChange: (tab: PlanTab) => void;
  isHuman: boolean;
  readOnly: boolean;
  onChanged: () => void;
}) {
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

  // The RoadMap is reviewed through RoadmapReview, which has its own For you | Raw text.
  const visible = useMemo(() => {
    if (tab === "info") return ["info"] as DocumentKind[];
    if (tab === "analysis") return [technical ? "analysis_ai" : "analysis"] as DocumentKind[];
    return [] as DocumentKind[];
  }, [tab, technical]);
  const roadmapTickets = ticketCount(reviewPlan(documents?.roadmap_ai.current_payload));

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
  // The text a person would approve is about to be replaced by the brief written for them.
  const writingForPeople = generation.writingForPeople;
  const canReviewScope =
    isHuman &&
    !writingForPeople &&
    scopeHasText &&
    scopeDocuments.every((kind) => {
      const document = documents?.[kind as DocumentKind];
      return document?.current_revision_id && document.state !== "stale";
    });
  const scope: PlanScope = tab === "analysis" ? "analysis" : "roadmap";
  const scopeLabel = tab === "analysis" ? "analysis" : "RoadMap";
  // An analysis brief carries "Approve analysis" at its end; the review below then leaves it out.
  const briefApproves =
    tab === "analysis" && !technical && !!documents && showsAnalysisBrief(documents.analysis);
  const { generating, visibleRun, activeRunId } = generation;
  const dismissRun = generating ? undefined : generation.dismissFailure;
  const generateDisabled = readOnly || generation.generate.isPending || generating;

  // A save while a run is in flight asks first; the question goes away by itself once the run ends,
  // so a later run cannot bring back a question nobody asked again.
  const [confirmInfoSave, setConfirmInfoSave] = useState(false);
  if (confirmInfoSave && activeRunId === null) setConfirmInfoSave(false);
  // A pending reset or save confirmation belongs to the document it was asked on, however the
  // document changed (its tab, or the header's next step).
  const [askedOn, setAskedOn] = useState(tab);
  if (askedOn !== tab) {
    setAskedOn(tab);
    setConfirmWithdraw(false);
    setConfirmInfoSave(false);
  }
  const saveInfoNow = () => {
    setConfirmInfoSave(false);
    planReview.saveInfo.mutate();
  };
  const requestInfoSave = () => {
    if (activeRunId === null) saveInfoNow();
    else setConfirmInfoSave(true);
  };
  const cancelRunThenSave = () => {
    if (activeRunId === null) saveInfoNow();
    else generation.cancelRun.mutate(activeRunId, { onSuccess: saveInfoNow });
  };

  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_15rem]">
      <div className="min-w-0">
        <LoopPlanTabs
          tab={tab}
          onTabChange={onTabChange}
          technical={tab === "analysis" && technical}
          onToggleTechnical={() => setTechnical((value) => !value)}
          agentId={agentId}
          onAgentChange={setAgentId}
          candidates={candidates}
          savedAgentName={savedAgentName}
          agentLocked={readOnly || generation.following}
          generating={generating}
          generateDisabled={generateDisabled}
          onGenerate={(purpose) => generation.generate.mutate(purpose)}
          onRewrite={
            readOnly || tab === "info"
              ? undefined
              : () => generation.generate.mutate(FOR_PEOPLE_PURPOSE[tab])
          }
          rewriteBlocked={rewriteBlockedReason({
            approved: approvedForScope,
            writing: writingForPeople,
            generating: generateDisabled,
            hasTechnical: Boolean(
              documents?.[tab === "roadmap" ? "roadmap_ai" : "analysis_ai"].current_content?.trim(),
            ),
          })}
        />
        {writingForPeople ? (
          <p role="status" className="mt-2 text-xs text-[var(--muted-foreground)]">
            A board agent is writing the brief of this {scopeLabel} for people. It can be approved
            when that is done.
          </p>
        ) : null}
        {/* Once, under the button that started the run; from 2xl the aside beside it shows it instead. */}
        {visibleRun ? (
          <GenerationRunPanel scope={scope} run={visibleRun} onDismiss={dismissRun} />
        ) : null}
        {tab !== "info" ? (
          <>
            <LastRunStatus
              scope={tab}
              lastRun={generation.lastRun}
              loading={generation.lastRunLoading}
            />
            <KeptCandidate
              run={generation.lastRun}
              scopeLabel={scopeLabel}
              regenerateDisabled={generateDisabled}
              onRegenerate={() => generation.generate.mutate(scope)}
            />
          </>
        ) : null}

        <div className="mt-3 flex flex-col gap-4">
          {tab === "roadmap" && documents ? <RoadmapReview documents={documents} /> : null}
          {visible.map((kind) => {
            const document = documents?.[kind];
            if (!document) return null;
            const technical = kind === "analysis" ? documents.analysis_ai.current_payload : null;
            const approval =
              kind === "analysis" && briefApproves
                ? {
                    revisionNumber: document.current_revision_number,
                    technicalRevisionNumber: documents.analysis_ai.current_revision_number,
                    approved: approvedForScope,
                    disabled: readOnly || !canReviewScope || planReview.review.isPending,
                    onApprove: () => {
                      planReview.review.mutate({ scope, decision: "approved" });
                    },
                  }
                : undefined;
            return (
              <PlanDocumentPanel
                key={kind}
                kind={kind}
                document={document}
                technical={technical}
                approval={approval}
              />
            );
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
              onSave={requestInfoSave}
              saveGuard={
                confirmInfoSave && activeRunId !== null ? (
                  <InfoSaveGuard
                    pending={generation.cancelRun.isPending || planReview.saveInfo.isPending}
                    onCancelRunFirst={cancelRunThenSave}
                    onSaveAnyway={saveInfoNow}
                    onBack={() => setConfirmInfoSave(false)}
                  />
                ) : undefined
              }
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
              approveInBrief={briefApproves}
              approved={approvedForScope}
              reviewPending={planReview.review.isPending}
              onDecision={(decision) => planReview.review.mutate({ scope, decision })}
              {...(tab === "roadmap"
                ? {
                    approveLabel: approveRoadmapLabel(roadmapTickets),
                    approveNote: approvalLine(documents?.roadmap, roadmapTickets),
                    quietReset: true,
                  }
                : {})}
            />
          )}
        </div>
      </div>
      {visibleRun ? (
        <GenerationRunAside scope={scope} run={visibleRun} onDismiss={dismissRun} />
      ) : null}
    </div>
  );
}
