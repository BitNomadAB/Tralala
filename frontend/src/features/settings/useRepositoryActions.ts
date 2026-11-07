import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { RepositoryDraft } from "./RepositoryDialog";

export const REPOSITORIES_KEY = ["repositories"];

/** "Rebuild mirror" removes the mirror so the next run clones it; "Remove now" retries a removal. */
export type MirrorAction = "rebuild" | "remove";

function payload(value: RepositoryDraft) {
  return {
    name: value.name.trim() || undefined,
    url: value.url.trim(),
    branch: value.branch.trim() || null,
    enabled: value.enabled,
    ...(value.token ? { token: value.token } : {}),
  };
}

/**
 * The Repositories page's commands, each with its toast: save, check access, delete and the two
 * mirror actions. Saving a new repository or a new key checks access right after. `checks` keeps
 * the last check's answer per repository until the list reloads it. A refused delete or mirror
 * removal reloads the list too, so a row the server kept shows why.
 */
export function useRepositoryActions(onSaved: () => void) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [checks, setChecks] = useState<Record<string, string>>({});

  const invalidate = () => queryClient.invalidateQueries({ queryKey: REPOSITORIES_KEY });
  const failed = (title: string) => (error: unknown) => {
    void invalidate();
    toast.push({ title, description: describeError(error), variant: "error" });
  };

  const check = useMutation({
    mutationFn: (repositoryId: string) => api.checkRepository(repositoryId),
    onSuccess: (result, repositoryId) => {
      setChecks((current) => ({
        ...current,
        [repositoryId]: `${result.status}: ${result.detail ?? ""}`,
      }));
      void invalidate();
      toast.push({
        title: result.status === "ok" ? "Access verified" : "Access failed",
        description: result.detail ?? undefined,
        variant: result.status === "ok" ? "success" : "error",
      });
    },
    onError: failed("Could not check access"),
  });

  const save = useMutation({
    mutationFn: (value: RepositoryDraft) =>
      value.id
        ? api.updateRepository(value.id, payload(value))
        : api.createRepository({ ...payload(value), provider: value.provider }),
    onSuccess: (repository, value) => {
      onSaved();
      void invalidate();
      toast.push({ title: "Repository saved", variant: "success" });
      // A new repository, or a new key, is checked at once the way a run reads it (its code, not
      // only that it exists), so a key that cannot read the code fails here and not in a run.
      if (!value.id || value.token) check.mutate(repository.id);
    },
    onError: failed("Could not save"),
  });

  const remove = useMutation({
    mutationFn: (repositoryId: string) => api.deleteRepository(repositoryId),
    onSuccess: () => {
      void invalidate();
      toast.push({ title: "Repository removed", variant: "success" });
    },
    onError: failed("Could not remove"),
  });

  const mirror = useMutation({
    mutationFn: ({ repositoryId, action }: { repositoryId: string; action: MirrorAction }) =>
      api.resetRepositoryMirror(repositoryId, action),
    onSuccess: (_repository, { action }) => {
      void invalidate();
      toast.push({
        title: "Mirror removed",
        description:
          action === "rebuild" ? "The next analysis or RoadMap run fetches it again." : undefined,
        variant: "success",
      });
    },
    onError: failed("Could not remove the mirror"),
  });

  return { save, check, remove, mirror, checks };
}
