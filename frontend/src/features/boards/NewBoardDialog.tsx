import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { AgentPicker } from "@/features/boards/AgentPicker";
import { RepositoryPicker } from "@/features/boards/RepositoryPicker";
import { ApiError, api } from "@/lib/api";
import { useTemplates } from "@/lib/queries";

/**
 * Creates a board, optionally from a template, and opens it. Always mounted, so a name typed and
 * then cancelled is still there next time; the template and the selections reset when the dialog
 * is dismissed.
 */
export function NewBoardDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [repositoryIds, setRepositoryIds] = useState<string[]>([]);
  const [agentIds, setAgentIds] = useState<string[]>([]);
  const { data: templates = [] } = useTemplates();
  const selectedTemplate = templates.find((template) => template.id === templateId) ?? null;

  const createMutation = useMutation({
    mutationFn: () =>
      api.createBoard({
        name: name.trim(),
        description: description.trim(),
        template_id: templateId || null,
        repository_ids: repositoryIds,
        agent_ids: agentIds,
      }),
    onSuccess: (board) => {
      void queryClient.invalidateQueries({ queryKey: ["boards"] });
      onOpenChange(false);
      setName("");
      setDescription("");
      setTemplateId("");
      setRepositoryIds([]);
      setAgentIds([]);
      toast.push({ title: "Board created", variant: "success" });
      void navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) => {
      toast.push({
        title: "Could not create board",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      });
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setTemplateId("");
          setRepositoryIds([]);
          setAgentIds([]);
        }
      }}
    >
      <DialogContent title="New board" description="A dedicated SQLite database is created for it.">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            createMutation.mutate();
          }}
        >
          <Field label="Name" htmlFor="board-name">
            <Input
              id="board-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
              maxLength={200}
            />
          </Field>
          <Field label="Start from" htmlFor="board-template">
            <Select
              id="board-template"
              value={templateId}
              onChange={(event) => {
                const next = event.target.value;
                setTemplateId(next);
                const template = templates.find((entry) => entry.id === next);
                setDescription(template ? template.description : "");
              }}
            >
              <option value="">Blank board (Backlog → Done)</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </Select>
          </Field>
          {selectedTemplate ? (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-xs">
              <p className="text-[var(--muted-foreground)]">
                {selectedTemplate.list_count > 0
                  ? `Lists: ${selectedTemplate.lists.join(" → ")}`
                  : "No lists saved; the default Backlog → Done lists are used."}
              </p>
              {selectedTemplate.labels.length > 0 ? (
                <p className="mt-1 text-[var(--muted-foreground)]">
                  Labels: {selectedTemplate.labels.map((label) => label.name).join(", ")}
                </p>
              ) : null}
            </div>
          ) : null}
          <RepositoryPicker selected={repositoryIds} onChange={setRepositoryIds} />
          <AgentPicker selected={agentIds} onChange={setAgentIds} />
          <Field label="Description" htmlFor="board-description">
            <Textarea
              id="board-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending || !name.trim()}>
              {createMutation.isPending ? "Creating…" : "Create board"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
