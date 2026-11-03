import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { useTemplates } from "@/lib/queries";
import type { BoardTemplate } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export function BoardTemplatesCard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: templates = [], isLoading } = useTemplates();
  const [deleting, setDeleting] = useState<BoardTemplate | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (template: BoardTemplate) => api.deleteTemplate(template.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
      setDeleting(null);
      toast.push({ title: "Template deleted", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete template",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Board templates</h2>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => {
            void navigate("/settings/templates/new");
          }}
        >
          <Plus size={14} /> New template
        </Button>
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Templates are stored in the registry database. Pick one when creating a board to prefill its
        description, lists and labels.
      </p>

      <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-[var(--border)]">
        {isLoading ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading templates…</p>
        ) : templates.length === 0 ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">
            No templates yet. Create one here or save a board as a template from its header.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {templates.map((template) => (
              <li key={template.id} className="flex items-start gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-sm font-medium">
                    <LayoutTemplate size={14} className="shrink-0 text-[var(--muted-foreground)]" />
                    <span className="truncate">{template.name}</span>
                  </p>
                  {template.description ? (
                    <p className="mt-0.5 line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {template.description}
                    </p>
                  ) : null}
                  <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                    {template.list_count > 0 ? template.lists.join(" · ") : "Default lists"} ·{" "}
                    {template.labels.length} label{template.labels.length === 1 ? "" : "s"} ·
                    updated {formatDateTime(template.updated_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={`Edit ${template.name}`}
                    onClick={() => {
                      void navigate(`/settings/templates/${template.id}`);
                    }}
                  >
                    <Pencil size={14} /> Edit
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Delete template"
                    aria-label={`Delete ${template.name}`}
                    onClick={() => setDeleting(template)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent
          title="Delete template"
          description="Boards created from it keep their content. This cannot be undone."
        >
          <p className="text-sm">
            Delete <span className="font-semibold">{deleting?.name}</span>?
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={deleteMutation.isPending}
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              Delete template
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
