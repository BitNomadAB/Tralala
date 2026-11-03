import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { ApiError, api } from "@/lib/api";
import type { Actor } from "@/lib/types";
import { AuthContext } from "./useAuth";

// Not `keys.me` from lib/queries: importing that module here would move every query hook out of
// the pages' shared chunk into the entry chunk.
const ME = ["me"] as const;

async function fetchActor(): Promise<Actor | null> {
  try {
    return await api.me();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ME,
    queryFn: fetchActor,
    staleTime: 30_000,
    retry: false,
  });

  /**
   * The one sign-out path (logout, a password change, every 401). It runs once per session: while
   * `me` is null there is nothing to forget, so a burst of 401s, or the 401 of a logout whose session
   * had already ended, does nothing more. `queryClient.clear()` is not used anywhere: it would also
   * drop `me` from under the observer above, so this provider would keep the old actor on screen and
   * every page would go on asking the server with a dead session.
   */
  const signOutLocally = useCallback(() => {
    if (queryClient.getQueryData(ME) === null) return;
    // A read of the session still on its way must not sign the user back in when it answers.
    void queryClient.cancelQueries({ queryKey: ME });
    // While the observer above is attached, so RequireAuth re-renders and redirects to /login.
    queryClient.setQueryData(ME, null);
    // Removing a query also cancels its fetch and any retry; the pages unmount with the redirect.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME[0] });
  }, [queryClient]);

  useEffect(() => {
    window.addEventListener("tralala:unauthorized", signOutLocally);
    return () => window.removeEventListener("tralala:unauthorized", signOutLocally);
  }, [signOutLocally]);

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: (actor) => queryClient.setQueryData(ME, actor),
  });

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(),
    onSettled: signOutLocally,
  });

  const login = useCallback(
    (username: string, password: string) => loginMutation.mutateAsync({ username, password }),
    [loginMutation],
  );
  const logout = useCallback(() => logoutMutation.mutateAsync(), [logoutMutation]);
  /** Re-read the session, for flows that sign in outside the login form (an invitation link). */
  const refresh = useCallback(async () => {
    const actor = await fetchActor();
    queryClient.setQueryData(ME, actor);
    return actor;
  }, [queryClient]);

  const value = useMemo(
    () => ({ actor: data ?? null, loading: isLoading, login, logout, refresh, signOutLocally }),
    [data, isLoading, login, logout, refresh, signOutLocally],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
