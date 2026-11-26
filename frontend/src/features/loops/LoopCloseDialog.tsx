import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useReadiness } from "@/lib/queries";
import type { Loop } from "@/lib/types";
import { OpenDelivery } from "./OpenDelivery";
import { PocUnanswered } from "./PocUnanswered";

/** What the completion dialog is given, for a Loop with a plan and for one without. */
export interface CompletionDialogProps {
  boardId: string;
  loop: Loop;
  open: boolean;
  isHuman: boolean;
  onClose: () => void;
  onChanged: () => void;
  /** The Loop's POC decisions not answered yet; a line says so, holding nothing up. */
  openDecisions?: number | undefined;
}

/**
 * The completion dialog of a Loop without a plan (`without_plan`): one decision of a signed-in
 * person closes it. It asks no QA question and has no QA section, and it warns about no work outside
 * a plan, since every Ticket of such a Loop is its work. The Tickets still open (`open_delivery`)
 * hold "Close the Loop" up until the person closes it without them; each one left then reads Not
 * done. The server reads only the version, the acceptance, the note and that choice.
 */
export function LoopCloseDialog({
  boardId,
  loop,
  open,
  isHuman,
  onClose,
  onChanged,
  openDecisions = 0,
}: CompletionDialogProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const unfinished = useReadiness(boardId, loop.id).data?.open_delivery ?? [];
  const [acceptUnfinished, setAcceptUnfinished] = useState(false);
  const heldByUnfinished = isHuman && unfinished.length > 0 && !acceptUnfinished;
  const unfinishedId = useId();

  const close = useMutation({
    mutationFn: () =>
      api.acceptImplementation(boardId, loop.id, {
        version: loop.version,
        accepted: true,
        note,
        accept_unfinished: acceptUnfinished && unfinished.length > 0,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loop.id) });
      void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loop.id) });
      void queryClient.invalidateQueries({ queryKey: keys.history(boardId, {}) });
      onChanged();
      toast.push({ title: "Loop closed", variant: "success" });
    },
    onError: (error) => {
      // A refusal for Tickets this dialog did not know were open shows them.
      void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loop.id) });
      toast.push({
        title: "Could not close the Loop",
        description: describeError(error),
        variant: "error",
      });
    },
  });

  const completed = loop.stage === "completed";

  return (
    <Dialog open={open} onOpenChange={(value) => (!value ? onClose() : undefined)}>
      <DialogContent
        title={completed ? `${loop.key} is completed` : `Close ${loop.key}`}
        description="One decision closes a Loop without a plan. No QA is asked for."
        className="w-[min(640px,96vw)]"
      >
        {completed ? (
          <p className="rounded-lg border border-[var(--success)] p-3 text-sm text-[var(--success)]">
            The Loop is closed and read-only. Board history shows it as closed without a plan.
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <PocUnanswered
              boardId={boardId}
              loopId={loop.id}
              open={openDecisions}
              onLeave={onClose}
            />
            <OpenDelivery
              tickets={unfinished}
              accepted={acceptUnfinished}
              onAcceptedChange={setAcceptUnfinished}
              reasonId={unfinishedId}
              disabled={!isHuman}
            />
            <Field label="Note (optional)" htmlFor="close-note">
              <Input
                id="close-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                disabled={!isHuman}
              />
            </Field>
            <div className="flex justify-end">
              <HeldButton
                held={close.isPending || heldByUnfinished}
                reasonId={heldByUnfinished ? unfinishedId : undefined}
                disabled={!isHuman}
                onClick={() => close.mutate()}
              >
                Close the Loop
              </HeldButton>
            </div>
            {!isHuman ? (
              <p className="text-xs text-[var(--warning)]">
                Only a signed-in person can close a Loop.
              </p>
            ) : null}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
