import { useQuery } from "@tanstack/react-query";
import { GitBranch } from "lucide-react";
import { api } from "@/lib/api";
import { RepositoryPathFields } from "./RepositoryPathFields";
import { EMPTY_PATHS_DRAFT, type RepositoryPathsDrafts } from "./repositoryPaths";

/**
 * Checkbox list of the repositories the installation knows about. The board's selection decides
 * which code the Analytics agent may inspect for that board's Loops. With `paths`, each selected
 * repository also takes the focus and exclude globs that narrow what is read of it.
 */
export function RepositoryPicker({
  selected,
  onChange,
  disabled,
  paths,
  onPathsChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
  paths?: RepositoryPathsDrafts | undefined;
  onPathsChange?: ((paths: RepositoryPathsDrafts) => void) | undefined;
}) {
  const repositoriesQuery = useQuery({
    queryKey: ["repositories"],
    queryFn: () => api.listRepositories(),
    staleTime: 60_000,
  });
  const repositories = repositoriesQuery.data ?? [];

  if (repositoriesQuery.isLoading) {
    return <p className="text-xs text-[var(--muted-foreground)]">Loading repositories…</p>;
  }
  if (repositories.length === 0) {
    return (
      <p className="text-xs text-[var(--muted-foreground)]">
        No repositories are registered yet. An administrator adds them under Settings → GitHub
        repositories.
      </p>
    );
  }

  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Repositories
      </legend>
      <p className="text-xs text-[var(--muted-foreground)]">
        Which code this board is about. The Analytics agent may inspect only what is selected.
      </p>
      <div className="flex flex-col gap-1 rounded-lg border border-[var(--border)] p-2">
        {repositories.map((repository) => {
          const isSelected = selected.includes(repository.id);
          return (
            <div key={repository.id} className="flex flex-col gap-1.5">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...selected, repository.id]
                        : selected.filter((id) => id !== repository.id),
                    )
                  }
                />
                <GitBranch size={13} className="text-[var(--muted-foreground)]" />
                <span className="font-medium">{repository.name}</span>
                <span className="truncate text-[11px] text-[var(--muted-foreground)]">
                  {repository.url}
                </span>
                {repository.has_token ? null : (
                  <span className="text-[11px] text-[var(--muted-foreground)]">(no token)</span>
                )}
              </label>
              {isSelected && paths && onPathsChange ? (
                <RepositoryPathFields
                  repositoryId={repository.id}
                  repositoryName={repository.name}
                  value={paths[repository.id] ?? EMPTY_PATHS_DRAFT}
                  disabled={disabled}
                  onChange={(value) => onPathsChange({ ...paths, [repository.id]: value })}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
