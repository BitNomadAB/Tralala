import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";

/** Saves the Loop's column names and the board's labels as a board template. */
export function SaveTemplateDialog({
  boardId,
  loopId,
  defaultName,
  defaultDescription,
  columnCount,
  onClose,
}: {
  boardId: string;
  loopId: string;
  defaultName: string;
  defaultDescription: string;
  columnCount: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(defaultName);
  const [description, setDescription] = useState(defaultDescription);

  const save = useMutation({
    mutationFn: () => api.saveBoardAsTemplate(boardId, loopId, { name: name.trim(), description }),
    onSuccess: () => {
      onClose();
      void queryClient.invalidateQueries({ queryKey: keys.templates });
      toast.push({ title: "Template saved", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not save template",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title="Save as template"
        description="Stores this Loop's column names and the board's labels for future Loops."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          <Field label="Template name" htmlFor="loop-template-name">
            <Input
              id="loop-template-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
              maxLength={200}
            />
          </Field>
          <Field label="Description" htmlFor="loop-template-description">
            <Textarea
              id="loop-template-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <p className="text-[11px] text-[var(--muted-foreground)]">
            Captures {columnCount} columns. Tickets are not copied.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              {save.isPending ? "Saving…" : "Save template"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
