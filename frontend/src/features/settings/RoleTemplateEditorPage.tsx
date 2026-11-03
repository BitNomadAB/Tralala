import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useRoleTemplate } from "@/lib/queries";
import type { RoleTemplate } from "@/lib/types";

export function RoleTemplateEditorPage() {
  const { roleId } = useParams();
  const isNew = !roleId || roleId === "new";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const roleQuery = useRoleTemplate(String(roleId));

  const [hydratedId, setHydratedId] = useState<string | null>(isNew ? "new" : null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [confirming, setConfirming] = useState(false);

  // Fill the form from the loaded role once per role, while rendering rather than in an effect.
  const loaded: RoleTemplate | undefined = roleQuery.data;
  if (loaded && hydratedId !== loaded.id) {
    setName(loaded.name);
    setDescription(loaded.description);
    setSystemPrompt(loaded.system_prompt);
    setHydratedId(loaded.id);
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["role-templates"] });

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        description,
        system_prompt: systemPrompt.trim(),
      };
      return isNew ? api.createRoleTemplate(payload) : api.updateRoleTemplate(roleId, payload);
    },
    onSuccess: (role) => {
      void invalidate();
      queryClient.setQueryData(["role-template", role.id], role);
      toast.push({ title: "Role template saved", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not save role template",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const duplicateMutation = useMutation({
    mutationFn: () => api.duplicateRoleTemplate(String(roleId)),
    onSuccess: (role) => {
      void invalidate();
      toast.push({ title: "Role duplicated", variant: "success" });
      void navigate(`/settings/roles/${role.id}`);
    },
    onError: (error) => {
      toast.push({
        title: "Could not duplicate role",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const restoreMutation = useMutation({
    mutationFn: () => api.restoreRoleTemplate(String(roleId)),
    onSuccess: (role) => {
      void invalidate();
      setSystemPrompt(role.system_prompt);
      toast.push({ title: "Factory prompt restored", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not restore defaults",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteRoleTemplate(String(roleId)),
    onSuccess: () => {
      void invalidate();
      setConfirming(false);
      toast.push({ title: "Role template deleted", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete role template",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  if (!isNew && roleQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading role template…</p>;
  }
  if (!isNew && roleQuery.error) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {describeError(roleQuery.error, "Role unavailable.")}
      </p>
    );
  }

  const role = roleQuery.data;

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
        <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold">
          {isNew ? "New role template" : `Edit ${name || "role"}`}
          {role?.built_in ? <Badge tone="neutral">built-in</Badge> : null}
          {role?.customized ? <Badge tone="brand">customized</Badge> : null}
        </h1>
        <p className="text-xs text-[var(--muted-foreground)]">
          Agents pick a role template. Saving changes here affects future discussions; existing
          discussions keep the snapshot they started with.
        </p>
      </div>

      <form
        className="card-surface flex flex-col gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() && systemPrompt.trim()) saveMutation.mutate();
        }}
      >
        <Field label="Name" htmlFor="role-name">
          <Input
            id="role-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={200}
            autoFocus
          />
        </Field>
        <Field label="Description" htmlFor="role-description">
          <Textarea
            id="role-description"
            className="min-h-16"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={20000}
          />
        </Field>
        <Field
          label="System prompt"
          htmlFor="role-prompt"
          hint="The role instructions sent to the model. Be explicit about the perspective and the expected verdict format."
        >
          <Textarea
            id="role-prompt"
            className="min-h-64 font-mono text-xs"
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            required
            maxLength={20000}
          />
        </Field>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] pt-3">
          {!isNew ? (
            <Button
              type="button"
              variant="danger"
              className="mr-auto"
              disabled={Boolean(role?.built_in)}
              title={role?.built_in ? "Built-in roles cannot be deleted" : "Delete role"}
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={14} /> Delete
            </Button>
          ) : null}
          {role?.built_in ? (
            <Button
              type="button"
              variant="outline"
              disabled={restoreMutation.isPending}
              onClick={() => restoreMutation.mutate()}
            >
              <RotateCcw size={14} /> Restore factory prompt
            </Button>
          ) : null}
          {!isNew ? (
            <Button
              type="button"
              variant="outline"
              disabled={duplicateMutation.isPending}
              onClick={() => duplicateMutation.mutate()}
            >
              <Copy size={14} /> Duplicate
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
          <Button
            type="submit"
            disabled={!name.trim() || !systemPrompt.trim() || saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving…" : "Save role"}
          </Button>
        </div>
      </form>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent title="Delete role template" description="This cannot be undone.">
          <p className="text-sm">
            Delete <span className="font-semibold">{name}</span>? Agents using it must be given
            another role or an override.
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
              Delete role
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
