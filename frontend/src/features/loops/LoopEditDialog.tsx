import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { Loop } from "@/lib/types";

/** "Edit Loop": its name and broad goal, saved against the version the page has. */
export function LoopEditDialog({
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
  const [name, setName] = useState(loop.name);
  const [goal, setGoal] = useState(loop.goal);

  const save = useMutation({
    mutationFn: () =>
      api.updateLoop(boardId, loop.id, { version: loop.version, name: name.trim(), goal }),
    onSuccess: () => {
      onChanged();
      onClose();
      toast.push({ title: "Loop saved", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not save the Loop",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent title="Edit Loop" description="The Loop's name and its broad goal.">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          <Field label="Name" htmlFor="edit-loop-name">
            <Input
              id="edit-loop-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
              maxLength={200}
            />
          </Field>
          <Field label="Broad goal" htmlFor="edit-loop-goal">
            <Textarea
              id="edit-loop-goal"
              rows={3}
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
