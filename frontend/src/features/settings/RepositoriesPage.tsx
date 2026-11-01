import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, GitBranch, KeyRound, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/features/auth/AuthProvider";

const REPOSITORIES_KEY = ["repositories"];

type Draft = {
  id: string | null;
  name: string;
  url: string;
  branch: string;
  token: string;
  enabled: boolean;
};

const EMPTY: Draft = {
  id: null,
  name: "",
  url: "",
  branch: "",
  token: "",
  enabled: true,
};

export function RepositoriesPage() {
  const { actor } = useAuth();
  const isAdmin = actor?.role === "admin";
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [checks, setChecks] = useState<Record<string, string>>({});

  const repositoriesQuery = useQuery({
    queryKey: REPOSITORIES_KEY,
    queryFn: () => api.listRepositories(),
    enabled: isAdmin,
  });
  const repositories = repositoriesQuery.data ?? [];

  const errorText = (error: unknown) =>
    error instanceof ApiError ? error.message : "Please try again.";
  const invalidate = () => queryClient.invalidateQueries({ queryKey: REPOSITORIES_KEY });

  const save = useMutation({
    mutationFn: (value: Draft) => {
      if (value.id) {
        return api.updateRepository(value.id, {
          name: value.name.trim() || undefined,
          url: value.url.trim(),
          branch: value.branch.trim() || null,
          enabled: value.enabled,
          ...(value.token ? { token: value.token } : {}),
        });
      }
      return api.createRepository({
        name: value.name.trim() || undefined,
        url: value.url.trim(),
        branch: value.branch.trim() || null,
        enabled: value.enabled,
        ...(value.token ? { token: value.token } : {}),
      });
    },
    onSuccess: () => {
      setDraft(null);
      invalidate();
      toast.push({ title: "Repository saved", variant: "success" });
    },
    onError: (error) =>
      toast.push({ title: "Could not save", description: errorText(error), variant: "error" }),
  });

  const check = useMutation({
    mutationFn: (repositoryId: string) => api.checkRepository(repositoryId),
    onSuccess: (result, repositoryId) => {
      setChecks((current) => ({ ...current, [repositoryId]: `${result.status}: ${result.detail ?? ""}` }));
      invalidate();
      toast.push({
        title: result.status === "ok" ? "Access verified" : "Access failed",
        description: result.detail ?? undefined,
        variant: result.status === "ok" ? "success" : "error",
      });
    },
    onError: (error) =>
      toast.push({ title: "Could not check access", description: errorText(error), variant: "error" }),
  });

  const remove = useMutation({
    mutationFn: (repositoryId: string) => api.deleteRepository(repositoryId),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "Repository removed", variant: "success" });
    },
    onError: (error) =>
      toast.push({ title: "Could not remove", description: errorText(error), variant: "error" }),
  });

  if (!isAdmin) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-lg font-semibold">GitHub repositories</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          Only an administrator manages repository access.
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-lg font-semibold">GitHub repositories</h1>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Read-only access for the Analytics agent. Boards select which repositories they are about;
            the token is stored sealed and never shown again.
          </p>
        </div>
        <Button size="sm" className="ml-auto" onClick={() => setDraft({ ...EMPTY })}>
          <Plus size={14} /> New repository
        </Button>
      </div>

      {repositoriesQuery.isLoading ? (
        <p className="text-xs text-[var(--muted-foreground)]">Loading repositories…</p>
      ) : repositories.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[var(--border)] p-4 text-xs text-[var(--muted-foreground)]">
          No repositories yet. Add one and assign it to the board whose Loops should analyse it.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {repositories.map((repository) => (
            <li key={repository.id} className="card-surface flex flex-col gap-2 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <GitBranch size={14} className="text-[var(--muted-foreground)]" />
                <span className="text-sm font-medium">{repository.name}</span>
                {repository.branch ? <Badge tone="neutral">{repository.branch}</Badge> : null}
                {repository.boards.length > 0 ? (
                  repository.boards.map((board) => (
                    <Badge key={board.id} tone="brand">
                      {board.name}
                    </Badge>
                  ))
                ) : (
                  <Badge tone="neutral">no board</Badge>
                )}
                {repository.has_token ? (
                  <Badge tone="success">
                    <KeyRound size={11} /> {repository.token_hint ?? "token"}
                  </Badge>
                ) : (
                  <Badge tone="warning">no token</Badge>
                )}
                {!repository.enabled ? <Badge tone="neutral">disabled</Badge> : null}
              </div>
              <p className="break-all text-[11px] text-[var(--muted-foreground)]">{repository.url}</p>
              {checks[repository.id] ?? repository.last_check_detail ? (
                <p className="flex items-center gap-1.5 text-[11px]">
                  <CheckCircle2 size={12} className="text-[var(--muted-foreground)]" />
                  {checks[repository.id] ?? `${repository.last_check_status}: ${repository.last_check_detail}`}
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => check.mutate(repository.id)}
                  disabled={check.isPending}
                >
                  Test access
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setDraft({
                      id: repository.id,
                      name: repository.name,
                      url: repository.url,
                      branch: repository.branch ?? "",
                      token: "",
                      enabled: repository.enabled,
                    })
                  }
                >
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => remove.mutate(repository.id)}
                  disabled={remove.isPending}
                >
                  <Trash2 size={13} /> Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {draft ? (
        <RepositoryDialog
          draft={draft}
          saving={save.isPending}
          hasToken={Boolean(repositories.find((item) => item.id === draft.id)?.has_token)}
          onChange={setDraft}
          onClose={() => setDraft(null)}
          onSave={() => save.mutate(draft)}
        />
      ) : null}
    </section>
  );
}

function RepositoryDialog({
  draft,
  saving,
  hasToken,
  onChange,
  onClose,
  onSave,
}: {
  draft: Draft;
  saving: boolean;
  hasToken: boolean;
  onChange: (value: Draft) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const update = (patch: Partial<Draft>) => onChange({ ...draft, ...patch });

  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent
        title={draft.id ? "Edit repository" : "New repository"}
        description="Read-only access for the Analysis agent. Only https://github.com/<owner>/<repository> is accepted."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.url.trim()) onSave();
          }}
        >
          <Field label="Name" htmlFor="repository-name" hint="Shown in lists; defaults to the repository name.">
            <Input
              id="repository-name"
              value={draft.name}
              onChange={(event) => update({ name: event.target.value })}
              maxLength={120}
            />
          </Field>
          <Field label="Repository URL" htmlFor="repository-url">
            <Input
              id="repository-url"
              value={draft.url}
              onChange={(event) => update({ url: event.target.value })}
              placeholder="https://github.com/BitNomadAB/Tralala"
              required
              maxLength={500}
            />
          </Field>
          <Field label="Branch (optional)" htmlFor="repository-branch" hint="Defaults to the default branch.">
            <Input
              id="repository-branch"
              value={draft.branch}
              onChange={(event) => update({ branch: event.target.value })}
              placeholder="main"
              maxLength={200}
            />
          </Field>
          <Field
            label="Access token"
            htmlFor="repository-token"
            hint={
              hasToken
                ? "A token is stored. Leave blank to keep it; enter a new one to replace it."
                : "Fine-grained token with Contents: read for this repository only."
            }
          >
            <Input
              id="repository-token"
              type="password"
              value={draft.token}
              onChange={(event) => update({ token: event.target.value })}
              autoComplete="off"
              maxLength={500}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => update({ enabled: event.target.checked })}
            />
            Enabled for analysis
          </label>
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={!draft.url.trim() || saving}>
              Save repository
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
