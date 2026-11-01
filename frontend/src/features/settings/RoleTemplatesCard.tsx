import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldHalf, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRoleTemplates } from "@/lib/queries";
import type { RoleTemplate } from "@/lib/types";

export function RoleTemplatesCard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: roles = [], isLoading } = useRoleTemplates();
  const [deleting, setDeleting] = useState<RoleTemplate | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (role: RoleTemplate) => api.deleteRoleTemplate(role.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-templates"] });
      setDeleting(null);
      toast.push({ title: "Role template deleted", variant: "success" });
    },
    onError: (error) =>
      toast.push({
        title: "Could not delete role template",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Role templates</h2>
        <Button size="sm" className="ml-auto" onClick={() => navigate("/settings/roles/new")}>
          <Plus size={14} /> New role
        </Button>
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Central role definitions. Agents reference a template; editing it changes future
        discussions only, because each discussion stores a snapshot of the instructions it used.
      </p>

      <div className="mt-3 max-h-72 overflow-y-auto rounded-lg border border-[var(--border)]">
        {isLoading ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading role templates…</p>
        ) : roles.length === 0 ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">No role templates yet.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {roles.map((role) => (
              <li key={role.id} className="flex items-start gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                    <ShieldHalf size={14} className="shrink-0 text-[var(--muted-foreground)]" />
                    <span className="truncate">{role.name}</span>
                    {role.built_in ? <Badge tone="neutral">built-in</Badge> : null}
                    {role.scope === "organisation" ? (
                      <Badge tone="success">organisation</Badge>
                    ) : null}
                    {role.customized ? <Badge tone="brand">customized</Badge> : null}
                  </p>
                  {role.description ? (
                    <p className="mt-0.5 line-clamp-2 text-xs text-[var(--muted-foreground)]">
                      {role.description}
                    </p>
                  ) : null}
                  <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
                    {role.agent_count} agent{role.agent_count === 1 ? "" : "s"} ·{" "}
                    {role.system_prompt.slice(0, 90)}
                    {role.system_prompt.length > 90 ? "…" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={`Edit ${role.name}`}
                    onClick={() => navigate(`/settings/roles/${role.id}`)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title={role.built_in ? "Built-in roles cannot be deleted" : "Delete role"}
                    aria-label={`Delete ${role.name}`}
                    disabled={role.built_in}
                    onClick={() => setDeleting(role)}
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
          title="Delete role template"
          description="Agents keep their history and discussion snapshots. Agents using it must then be given another role or an override."
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
              Delete role
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
