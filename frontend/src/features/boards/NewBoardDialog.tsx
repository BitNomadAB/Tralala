import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { useToast } from "@/components/ui/useToast";
import { AgentPicker } from "@/features/boards/AgentPicker";
import { pathsPayload, type RepositoryPathsDrafts } from "@/features/boards/repositoryPaths";
import { RepositoryPicker } from "@/features/boards/RepositoryPicker";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useTemplates } from "@/lib/queries";
import { useTemplateDescription } from "./useTemplateDescription";

const DESCRIPTION_ID = "board-description";

/**
 * Creates a board, optionally from a template, and opens it. Always mounted, so a name typed and
 * then cancelled is still there next time; the template and the selections reset when the dialog
 * is dismissed. A template fills in its description only while the person has not written one;
 * words they wrote stay, with the template's offered beside the choice (WCAG 3.3.4).
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
  const announce = useAnnounce();
  const [name, setName] = useState("");
  const descriptionField = useTemplateDescription();
  const { description } = descriptionField;
  const [templateId, setTemplateId] = useState("");
  const [repositoryIds, setRepositoryIds] = useState<string[]>([]);
  const [repositoryPaths, setRepositoryPaths] = useState<RepositoryPathsDrafts>({});
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
        repository_paths: pathsPayload(repositoryPaths, repositoryIds),
        agent_ids: agentIds,
      }),
    onSuccess: (board) => {
      void queryClient.invalidateQueries({ queryKey: ["boards"] });
      onOpenChange(false);
      setName("");
      descriptionField.clear();
      setTemplateId("");
      setRepositoryIds([]);
      setRepositoryPaths({});
      setAgentIds([]);
      toast.push({ title: "Board created", variant: "success" });
      void navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) => {
      toast.push({
        title: "Could not create board",
        description: describeError(mutationError, undefined),
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
          descriptionField.dropOffer();
          setRepositoryIds([]);
          setRepositoryPaths({});
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
                const choice = descriptionField.choose(template ? template.description : "");
                if (choice === "kept" && template?.description) {
                  announce(
                    "Your description is kept. The next button, Use the template's description, replaces it.",
                  );
                }
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
              {descriptionField.offer !== null ? (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <p>The template has its own description; yours is kept.</p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      descriptionField.takeOffer();
                      // The button goes once it is used; the text it brought is where focus goes.
                      document.getElementById(DESCRIPTION_ID)?.focus();
                    }}
                  >
                    Use the template&apos;s description
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
          <RepositoryPicker
            selected={repositoryIds}
            onChange={setRepositoryIds}
            paths={repositoryPaths}
            onPathsChange={setRepositoryPaths}
          />
          <AgentPicker selected={agentIds} onChange={setAgentIds} />
          <Field label="Description" htmlFor={DESCRIPTION_ID}>
            <Textarea
              id={DESCRIPTION_ID}
              value={description}
              onChange={(event) => descriptionField.write(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <HeldButton type="submit" held={createMutation.isPending} disabled={!name.trim()}>
              {createMutation.isPending ? "Creating…" : "Create board"}
            </HeldButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
