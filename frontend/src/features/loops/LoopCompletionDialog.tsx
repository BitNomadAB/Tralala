import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useQaCycle } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { UnplannedWarning } from "./Unplanned";

type QaStatus = "not_tested" | "tested_with_issues" | "passed";
type ResultStatus = "passed" | "failed" | "blocked" | "not_run" | "not_applicable";

const RESULT_OPTIONS: { value: ResultStatus; label: string }[] = [
  { value: "passed", label: "Passed" },
  { value: "failed", label: "Failed" },
  { value: "blocked", label: "Blocked" },
  { value: "not_run", label: "Not run" },
  { value: "not_applicable", label: "Not applicable" },
];

export function LoopCompletionDialog({
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
      }),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "Implementation accepted", variant: "success" });
    },
    onError: (error) => {
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
              {loop.progress.ticket_completed < loop.progress.ticket_total ? (
                <p className="text-xs text-[var(--warning)]">
                  {loop.progress.ticket_total - loop.progress.ticket_completed} delivery ticket(s)
                  are still open; acceptance will be rejected until they are completed.
                </p>
              ) : null}
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
                <Button disabled={!isHuman || accept.isPending} onClick={() => accept.mutate()}>
                  {qaStatus === "passed" ? "Accept and complete the Loop" : "Accept implementation"}
                </Button>
              </div>
              {!isHuman ? (
                <p className="text-[11px] text-[var(--warning)]">
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
                {scenarios.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-[var(--border)] p-2 text-xs text-[var(--muted-foreground)]">
                    No QA instructions yet. Generate them with a configured agent, or supply a
                    scenario set through the API.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {scenarios.map((scenario) => (
                      <li
                        key={scenario.id}
                        className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] px-2 py-1.5"
                      >
                        <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
                          {scenario.id}
                        </span>
                        <span className="text-sm">{scenario.title}</span>
                        <Select
                          className="ml-auto h-7 w-auto"
                          aria-label={`Result for ${scenario.id}`}
                          value={draftResults[scenario.id] ?? ""}
                          onChange={(event) =>
                            setDraftResults((current) => ({
                              ...current,
                              [scenario.id]: event.target.value as ResultStatus,
                            }))
                          }
                        >
                          <option value="">Not recorded</option>
                          {RESULT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </Select>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    variant="outline"
                    disabled={Object.keys(draftResults).length === 0 || submitResults.isPending}
                    onClick={() => submitResults.mutate()}
                  >
                    Record results
                  </Button>
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
                  <Button
                    variant="outline"
                    disabled={!isHuman || decide.isPending}
                    onClick={() => decide.mutate("rejected")}
                  >
                    <XCircle size={14} /> Reject QA
                  </Button>
                  <Button
                    disabled={!isHuman || decide.isPending}
                    onClick={() => decide.mutate("accepted")}
                  >
                    <CheckCircle2 size={14} /> Accept QA and complete
                  </Button>
                </div>
              </section>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
