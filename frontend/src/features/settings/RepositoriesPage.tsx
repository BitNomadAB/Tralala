import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { usePageTitle } from "@/app/usePageTitle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import type { Repository } from "@/lib/types";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { entryControlId, removalFocusTarget, useRemovalFocus } from "./removalFocus";
import { RepositoryDialog, type RepositoryDraft } from "./RepositoryDialog";
import { RepositoryRow } from "./RepositoryRow";
import { REPOSITORIES_KEY, useRepositoryActions } from "./useRepositoryActions";

const HEADING_ID = "repositories-heading";
const checkId = (repositoryId: string) => entryControlId("repository-check", repositoryId);

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

/** What removing `repository` takes away, asked first: it cannot be undone (WCAG 3.3.4). */
function removeQuestion(repository: Repository): Confirmation {
  const mirror = repository.provider === "git_https" ? ", and deletes Tralala's mirror of it" : "";
  const boards = repository.boards.map((board) => board.name);
  const used =
    boards.length === 0
      ? ""
      : ` ${boards.length === 1 ? "The board" : "The boards"} ${boards.join(", ")} can no longer read it.`;
  return {
    title: `Remove ${repository.name}?`,
    consequence: `This removes the repository and its stored key from Tralala${mirror}.${used} This cannot be undone.`,
    confirmLabel: "Remove repository",
  };
}

export function RepositoriesPage() {
  const { actor } = useAuth();
  usePageTitle({ page: "repositories" });
  const isAdmin = actor?.role === "admin";
  const [draft, setDraft] = useState<RepositoryDraft | null>(null);
  const [removing, setRemoving] = useState<Repository | null>(null);
  const removalFocus = useRemovalFocus();
  const { save, check, remove, mirror, checks } = useRepositoryActions(() => setDraft(null));

  const repositoriesQuery = useQuery({
    queryKey: REPOSITORIES_KEY,
    queryFn: () => api.listRepositories(),
    enabled: isAdmin,
  });
  const repositories = repositoriesQuery.data ?? [];

  // A removed repository's row goes with its buttons, so the dialog stays open until it is gone
  // and then gives focus to the next row; after a refusal, back to the row's Remove button.
  function removeRepository(repositoryId: string) {
    const target = removalFocusTarget(
      repositories.map((repository) => repository.id),
      repositoryId,
      checkId,
      HEADING_ID,
    );
    remove.mutate(repositoryId, {
      onSuccess: () => {
        removalFocus.remember(target);
        setRemoving(null);
      },
      onError: () => setRemoving(null),
    });
  }

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
          <h1 id={HEADING_ID} tabIndex={-1} className="text-lg font-semibold">
            Repositories
          </h1>
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
              checkId={checkId(repository.id)}
              checkText={checks[repository.id]}
              busy={{
                check: check.isPending && check.variables === repository.id,
                remove: remove.isPending && remove.variables === repository.id,
                mirror: mirror.isPending && mirror.variables.repositoryId === repository.id,
              }}
              onCheck={() => check.mutate(repository.id)}
              onEdit={() => setDraft(draftOf(repository))}
              onRemove={() => setRemoving(repository)}
              onMirror={(action) => mirror.mutate({ repositoryId: repository.id, action })}
            />
          ))}
        </ul>
      )}

      <ConfirmDialog
        question={removing ? removeQuestion(removing) : null}
        busy={remove.isPending ? "Removing…" : null}
        onCancel={() => {
          // Once asked, the removal is under way; the dialog closes when it is done.
          if (!remove.isPending) setRemoving(null);
        }}
        onConfirm={() => {
          if (removing) removeRepository(removing.id);
        }}
        onCloseAutoFocus={removalFocus.onCloseAutoFocus}
      />

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
