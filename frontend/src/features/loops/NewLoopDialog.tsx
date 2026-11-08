import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";

/** "New Loop": a name and a broad goal; creating it opens the new Loop's page. */
export function NewLoopDialog({
  boardId,
  open,
  onOpenChange,
}: {
  boardId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");

  const createLoop = useMutation({
    mutationFn: () => api.createLoop(boardId, { name: name.trim(), goal }),
    onSuccess: (loop) => {
      onOpenChange(false);
      setName("");
      setGoal("");
      void queryClient.invalidateQueries({ queryKey: ["loops", boardId] });
      void queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
      toast.push({ title: "Loop created", variant: "success" });
      void navigate(`/boards/${boardId}/loops/${loop.id}`);
    },
    onError: (error) => {
      toast.push({
        title: "Could not create the Loop",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New Loop"
        description="A Loop owns its own Kanban and planning documents. It starts empty."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) createLoop.mutate();
          }}
        >
          <Field label="Name" htmlFor="loop-name">
            <Input
              id="loop-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
              maxLength={200}
            />
          </Field>
          <Field label="Broad goal" htmlFor="loop-goal">
            <Textarea
              id="loop-goal"
              rows={3}
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || createLoop.isPending}>
              {createLoop.isPending ? "Creating…" : "Create Loop"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
