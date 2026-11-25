import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useQaCycle, useReadiness } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { LoopCloseDialog, type CompletionDialogProps } from "./LoopCloseDialog";
import { OpenDelivery } from "./OpenDelivery";
import { QaScenarioResults, type ResultStatus } from "./QaScenarioResults";
import { UnplannedWarning } from "./Unplanned";

type QaStatus = "not_tested" | "tested_with_issues" | "passed";

/**
 * The dialog that completes a Loop: for a Loop without a plan the one decision that closes it
 * (`LoopCloseDialog`), else the acceptance of the implementation and the QA below.
 */
export function LoopCompletionDialog(props: CompletionDialogProps) {
  return props.loop.without_plan ? (
    <LoopCloseDialog {...props} />
  ) : (
    <PlannedCompletionDialog {...props} />
  );
}

function PlannedCompletionDialog({
  boardId,
  loop,
  open,
  isHuman,
  onClose,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  open: boolean;
  isHuman: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const qaQuery = useQaCycle(boardId, loop.id, open && Boolean(loop.qa));
  const [qaStatus, setQaStatus] = useState<QaStatus>("not_tested");
  const [scope, setScope] = useState("");
  const [results, setResults] = useState("");
  const [note, setNote] = useState("");
  const [draftResults, setDraftResults] = useState<Record<string, ResultStatus>>({});
  const [notApplicable, setNotApplicable] = useState<string[]>([]);
  // Delivery Tickets that are not done hold the acceptance up until the person accepts without them.
  const unfinished = useReadiness(boardId, loop.id).data?.open_delivery ?? [];
  const [acceptUnfinished, setAcceptUnfinished] = useState(false);
  const heldByUnfinished = isHuman && unfinished.length > 0 && !acceptUnfinished;
  const unfinishedId = useId();

  const scenarios = useMemo(() => {
    const instructions = qaQuery.data?.human_instructions as
      { scenarios?: { id: string; title: string }[] } | undefined;
    return instructions?.scenarios ?? [];
  }, [qaQuery.data]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: keys.qa(boardId, loop.id) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loop.id) });
    void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loop.id) });
    void queryClient.invalidateQueries({ queryKey: keys.history(boardId, {}) });
    onChanged();
  };

  const accept = useMutation({
    mutationFn: () =>
      api.acceptImplementation(boardId, loop.id, {
        version: loop.version,
        accepted: true,
        qa_status: qaStatus,
        attestation:
          qaStatus === "passed" ? { scope, results, environment: "", evidence: note } : {},
        note,
        accept_unfinished: acceptUnfinished && unfinished.length > 0,
      }),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "Implementation accepted", variant: "success" });
    },
    onError: (error) => {
      // A refusal for Tickets this dialog did not know were open shows them.
      void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loop.id) });
      toast.push({
        title: "Could not accept",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const submitResults = useMutation({
    mutationFn: () =>
      api.submitQaResults(boardId, loop.id, {
        results: Object.entries(draftResults).map(([scenarioId, status]) => ({
          scenario_id: scenarioId,
          status,
          reason: status === "not_applicable" ? "Not applicable" : "",
          evidence: "",
        })),
      }),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "QA results recorded", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record results",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const decide = useMutation({
    mutationFn: (decision: "accepted" | "rejected") =>
      api.decideQa(boardId, loop.id, {
        version: loop.version,
        cycle_id: qaQuery.data?.id ?? "",
        decision,
        not_applicable_approvals: notApplicable,
        note,
      }),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "QA decision recorded", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not record the decision",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const completed = loop.stage === "completed";

  return (
    <Dialog open={open} onOpenChange={(value) => (!value ? onClose() : undefined)}>
      <DialogContent
        title={completed ? `${loop.key} is completed` : `${loop.key} completion and QA`}
        description="Accepting implementation and accepting QA are separate human decisions."
        className="w-[min(880px,96vw)]"
      >
        {completed ? (
          <p className="rounded-lg border border-[var(--success)] p-3 text-sm text-[var(--success)]">
            The Loop is completed and read-only. Its immutable snapshot is available in Board
            history.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-medium">1. Accept the implementation</h2>
              <OpenDelivery
                tickets={unfinished}
                accepted={acceptUnfinished}
                onAcceptedChange={setAcceptUnfinished}
                reasonId={unfinishedId}
                disabled={!isHuman}
              />
              <UnplannedWarning boardId={boardId} loopId={loop.id} />
              <fieldset className="flex flex-col gap-2">
                <legend className="text-xs text-[var(--muted-foreground)]">
                  Was QA performed?
                </legend>
                <Select
                  aria-label="QA status"
                  value={qaStatus}
                  onChange={(event) => setQaStatus(event.target.value as QaStatus)}
                  disabled={!isHuman}
                >
                  <option value="not_tested">Not tested yet</option>
                  <option value="tested_with_issues">Tested with failures or gaps</option>
                  <option value="passed">Tested and passed outside Tralala</option>
                </Select>
              </fieldset>
              {qaStatus === "passed" ? (
                <>
                  <Field label="What was tested" htmlFor="qa-scope">
                    <Input
                      id="qa-scope"
                      value={scope}
                      onChange={(event) => setScope(event.target.value)}
                      disabled={!isHuman}
                    />
                  </Field>
                  <Field label="Results" htmlFor="qa-attestation-results">
                    <Textarea
                      id="qa-attestation-results"
                      rows={2}
                      value={results}
                      onChange={(event) => setResults(event.target.value)}
                      disabled={!isHuman}
                    />
                  </Field>
                </>
              ) : null}
              <Field label="Note (optional)" htmlFor="qa-note">
                <Input
                  id="qa-note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  disabled={!isHuman}
                />
              </Field>
              <div className="flex justify-end">
                <HeldButton
                  held={accept.isPending || heldByUnfinished}
                  reasonId={heldByUnfinished ? unfinishedId : undefined}
                  disabled={!isHuman}
                  onClick={() => accept.mutate()}
                >
                  {qaStatus === "passed" ? "Accept and complete the Loop" : "Accept implementation"}
                </HeldButton>
              </div>
              {!isHuman ? (
                <p className="text-xs text-[var(--warning)]">
                  Only a signed-in person can accept implementation or QA.
                </p>
              ) : null}
            </section>

            {loop.qa ? (
              <section className="flex flex-col gap-2 border-t border-[var(--border)] pt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-medium">2. Quality assurance</h2>
                  <Badge tone={loop.qa.status === "accepted" ? "success" : "warning"}>
                    cycle {loop.qa.cycle_number} · {loop.qa.status.replace("_", " ")}
                  </Badge>
                </div>
                <p className="text-xs text-[var(--muted-foreground)]">
                  One QA Task in the Kanban carries both an agent view and a human view built from
                  the same scenario ids.
                </p>
                <QaScenarioResults
                  scenarios={scenarios}
                  results={draftResults}
                  onResultChange={(scenarioId, status) =>
                    setDraftResults((current) => ({ ...current, [scenarioId]: status }))
                  }
                />
                <div className="flex flex-wrap justify-end gap-2">
                  <HeldButton
                    variant="outline"
                    held={submitResults.isPending}
                    disabled={Object.keys(draftResults).length === 0}
                    onClick={() => submitResults.mutate()}
                  >
                    Record results
                  </HeldButton>
                  <Select
                    aria-label="Scenarios approved as not applicable"
                    className="h-8 w-auto"
                    value={notApplicable[0] ?? ""}
                    onChange={(event) =>
                      setNotApplicable(event.target.value ? [event.target.value] : [])
                    }
                  >
                    <option value="">No not-applicable waivers</option>
                    {scenarios.map((scenario) => (
                      <option key={scenario.id} value={scenario.id}>
                        Waive {scenario.id}
                      </option>
                    ))}
                  </Select>
                  <HeldButton
                    variant="outline"
                    held={decide.isPending}
                    disabled={!isHuman}
                    onClick={() => decide.mutate("rejected")}
                  >
                    <XCircle size={14} /> Reject QA
                  </HeldButton>
                  <HeldButton
                    held={decide.isPending}
                    disabled={!isHuman}
                    onClick={() => decide.mutate("accepted")}
                  >
                    <CheckCircle2 size={14} /> Accept QA and complete
                  </HeldButton>
                </div>
              </section>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
