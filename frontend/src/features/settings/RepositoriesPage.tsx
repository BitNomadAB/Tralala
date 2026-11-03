import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import type { Repository } from "@/lib/types";
import { RepositoryDialog, type RepositoryDraft } from "./RepositoryDialog";
import { RepositoryRow } from "./RepositoryRow";
import { REPOSITORIES_KEY, useRepositoryActions } from "./useRepositoryActions";

const EMPTY: RepositoryDraft = {
  id: null,
  name: "",
  provider: "github",
  url: "",
  branch: "",
  token: "",
  enabled: true,
};

function draftOf(repository: Repository): RepositoryDraft {
  return {
    id: repository.id,
    name: repository.name,
    provider: repository.provider,
    url: repository.url,
    branch: repository.branch ?? "",
    token: "",
    enabled: repository.enabled,
  };
}

export function RepositoriesPage() {
  const { actor } = useAuth();
  const isAdmin = actor?.role === "admin";
  const [draft, setDraft] = useState<RepositoryDraft | null>(null);
  const { save, check, remove, mirror, checks } = useRepositoryActions(() => setDraft(null));

  const repositoriesQuery = useQuery({
    queryKey: REPOSITORIES_KEY,
    queryFn: () => api.listRepositories(),
    enabled: isAdmin,
  });
  const repositories = repositoriesQuery.data ?? [];

  if (!isAdmin) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-lg font-semibold">Repositories</h1>
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
          <h1 className="text-lg font-semibold">Repositories</h1>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Read-only access for the Analytics agent, through the GitHub API or a mirror Tralala
            keeps of any allowed HTTPS Git host. Boards select which repositories they are about;
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
            <RepositoryRow
              key={repository.id}
              repository={repository}
              checkText={checks[repository.id]}
              busy={{
                check: check.isPending,
                remove: remove.isPending,
                mirror: mirror.isPending,
              }}
              onCheck={() => check.mutate(repository.id)}
              onEdit={() => setDraft(draftOf(repository))}
              onRemove={() => remove.mutate(repository.id)}
              onMirror={(action) => mirror.mutate({ repositoryId: repository.id, action })}
            />
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
