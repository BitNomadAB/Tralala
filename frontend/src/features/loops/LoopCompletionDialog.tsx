import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useReadiness } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { OpenDelivery } from "./OpenDelivery";
import { QaDecision } from "./QaDecision";
import { UnplannedWarning } from "./Unplanned";

type QaStatus = "not_tested" | "tested_with_issues" | "passed";

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
  const [qaStatus, setQaStatus] = useState<QaStatus>("not_tested");
  const [scope, setScope] = useState("");
  const [results, setResults] = useState("");
  const [note, setNote] = useState("");
  // Delivery Tickets that are not done hold the acceptance up until the person accepts without them.
  const unfinished = useReadiness(boardId, loop.id).data?.open_delivery ?? [];
  const [acceptUnfinished, setAcceptUnfinished] = useState(false);
  const heldByUnfinished = isHuman && unfinished.length > 0 && !acceptUnfinished;
  const unfinishedId = useId();

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
              <QaDecision
                boardId={boardId}
                loop={loop}
                qa={loop.qa}
                isHuman={isHuman}
                note={note}
                onChanged={invalidate}
              />
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
