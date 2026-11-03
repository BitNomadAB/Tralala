import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import type { BoardTemplate } from "@/lib/types";
import { TemplateLabelsField, type LabelDraft } from "./TemplateLabelsField";
import { TemplateListsField } from "./TemplateListsField";

export function TemplateEditorPage() {
  const { templateId } = useParams();
  const isNew = !templateId || templateId === "new";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  const templateQuery = useQuery({
    queryKey: ["template", templateId],
    queryFn: () => api.getTemplate(String(templateId)),
    enabled: !isNew,
  });

  const [hydratedId, setHydratedId] = useState<string | null>(isNew ? "new" : null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [lists, setLists] = useState<string[]>([""]);
  const [labels, setLabels] = useState<LabelDraft[]>([]);
  const [confirming, setConfirming] = useState(false);

  // Fill the form from the loaded template once per template, while rendering rather than in an
  // effect.
  const loaded: BoardTemplate | undefined = templateQuery.data;
  if (loaded && hydratedId !== loaded.id) {
    setName(loaded.name);
    setDescription(loaded.description);
    setLists(loaded.lists.length > 0 ? loaded.lists : [""]);
    setLabels(loaded.labels.map((label) => ({ name: label.name, color: label.color })));
    setHydratedId(loaded.id);
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["templates"] });

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        description,
        lists: lists.map((entry) => entry.trim()).filter(Boolean),
        labels: labels
          .map((label) => ({ name: label.name.trim(), color: label.color }))
          .filter((label) => label.name.length > 0),
      };
      return isNew ? api.createTemplate(payload) : api.updateTemplate(templateId, payload);
    },
    onSuccess: (template) => {
      void invalidate();
      queryClient.setQueryData(["template", template.id], template);
      toast.push({ title: "Template saved", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not save template",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteTemplate(String(templateId)),
    onSuccess: () => {
      void invalidate();
      setConfirming(false);
      toast.push({ title: "Template deleted", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete template",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  if (!isNew && templateQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading template…</p>;
  }

  if (!isNew && templateQuery.error) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {templateQuery.error instanceof ApiError
          ? templateQuery.error.message
          : "Template unavailable."}
      </p>
    );
  }

  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <div>
        <button
          type="button"
          onClick={() => {
            void navigate("/settings");
          }}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={14} /> Settings
        </button>
        <h1 className="mt-1 text-xl font-semibold">
          {isNew ? "New board template" : `Edit ${name || "template"}`}
        </h1>
        <p className="text-xs text-[var(--muted-foreground)]">
          Stored in the registry database. Boards created from this template start with these lists
          and labels, and inherit the description unless one is typed.
        </p>
      </div>

      <form
        className="card-surface flex flex-col gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) saveMutation.mutate();
        }}
      >
        <Field label="Name" htmlFor="template-name">
          <Input
            id="template-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </Field>
        <Field label="Description" htmlFor="template-description">
          <Textarea
            id="template-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={20000}
          />
        </Field>

        <TemplateListsField lists={lists} onListsChange={setLists} />

        <TemplateLabelsField labels={labels} onLabelsChange={setLabels} />

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] pt-3">
          {!isNew ? (
            <Button
              type="button"
              variant="danger"
              className="mr-auto"
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={14} /> Delete template
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              void navigate("/settings");
            }}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!name.trim() || saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : "Save template"}
          </Button>
        </div>
      </form>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent
          title="Delete template"
          description="Boards created from it keep their content. This cannot be undone."
        >
          <p className="text-sm">
            Delete <span className="font-semibold">{name}</span>?
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              Delete template
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
