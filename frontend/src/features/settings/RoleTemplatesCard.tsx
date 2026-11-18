import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldHalf, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useRoleTemplates } from "@/lib/queries";
import type { RoleTemplate } from "@/lib/types";
import { ButtonLink } from "./ButtonLink";
import { entryControlId, removalFocusTarget, useRemovalFocus } from "./removalFocus";

const HEADING_ID = "settings-role-templates";
const editId = (roleId: string) => entryControlId("role-edit", roleId);

export function RoleTemplatesCard() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: roles = [], isLoading } = useRoleTemplates();
  const [deleting, setDeleting] = useState<RoleTemplate | null>(null);
  const removalFocus = useRemovalFocus();

  const deleteMutation = useMutation({
    mutationFn: (role: RoleTemplate) => api.deleteRoleTemplate(role.id),
    onSuccess: (_result, role) => {
      removalFocus.remember(
        removalFocusTarget(
          roles.map((entry) => entry.id),
          role.id,
          editId,
          HEADING_ID,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["role-templates"] });
      setDeleting(null);
      toast.push({ title: "Role template deleted", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete role template",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={HEADING_ID} tabIndex={-1} className="text-sm font-semibold">
          Role templates
        </h2>
        <ButtonLink to="/settings/roles/new" size="sm" className="ml-auto">
          <Plus size={14} /> New role
        </ButtonLink>
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Central role definitions. Agents reference a template; editing it changes future discussions
        only, because each discussion stores a snapshot of the instructions it used. Built-in roles
        cannot be deleted; their factory prompt can be restored instead.
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
                    <span className="min-w-0 break-words">{role.name}</span>
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
                  <p className="mt-1 break-words text-xs text-[var(--muted-foreground)]">
                    {role.agent_count} agent{role.agent_count === 1 ? "" : "s"} ·{" "}
                    {role.system_prompt.slice(0, 90)}
                    {role.system_prompt.length > 90 ? "…" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <ButtonLink
                    id={editId(role.id)}
                    to={`/settings/roles/${role.id}`}
                    size="sm"
                    variant="secondary"
                    aria-label={`Edit ${role.name}`}
                  >
                    Edit
                  </ButtonLink>
                  {/* A built-in role cannot be deleted, which the card says in words; a blank
                      keeps the Edit links of every row in one column. */}
                  {role.built_in ? (
                    <span aria-hidden="true" className="h-8 w-8" />
                  ) : (
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Delete role"
                      aria-label={`Delete ${role.name}`}
                      onClick={() => setDeleting(role)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
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
          onCloseAutoFocus={removalFocus.onCloseAutoFocus}
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
