import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { Loop } from "@/lib/types";

/** "Cancel Loop": asks first, because a cancelled Loop is read-only for good. */
export function LoopCancelDialog({
  boardId,
  loop,
  onClose,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState("");

  const cancel = useMutation({
    mutationFn: () =>
      api.cancelLoop(boardId, loop.id, {
        version: loop.version,
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      }),
    onSuccess: () => {
      onChanged();
      onClose();
      toast.push({ title: "Loop cancelled", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not cancel the Loop",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title="Cancel Loop"
        description="A cancelled Loop keeps its documents and Tickets but can no longer change. Its Tickets still take comments."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            cancel.mutate();
          }}
        >
          <Field label="Why (optional)" htmlFor="cancel-loop-reason">
            <Textarea
              id="cancel-loop-reason"
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={onClose}>
              Keep the Loop
            </Button>
            <Button type="submit" variant="danger" disabled={cancel.isPending}>
              {cancel.isPending ? "Cancelling…" : "Cancel Loop"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
