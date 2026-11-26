import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { Actor } from "@/lib/types";
import { AuthContext, type SignOutOptions } from "./useAuth";

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
   * Whether the login page drops the address it was sent from: set by a sign-out the person asked
   * for, cleared when the next session begins. A 401 never changes it, so after any sign-in a
   * session that ends by itself keeps the address. A page load starts with it cleared.
   */
  const [addressForgotten, setAddressForgotten] = useState(false);

  /**
   * The one sign-out path (logout, a password change, every 401). It runs once per session: while
   * `me` is null there is nothing to forget, so a burst of 401s, or the 401 of a logout whose session
   * had already ended, does nothing more. `queryClient.clear()` is not used anywhere: it would also
   * drop `me` from under the observer above, so this provider would keep the old actor on screen and
   * every page would go on asking the server with a dead session.
   *
   * `forgetAddress` is a sign-out the person asked for: the next sign-in opens the dashboard, so
   * whoever signs in next does not land on the page the last person left. A session that ended by
   * itself keeps the address, and the sign-in returns the person to where they were.
   */
  const signOutLocally = useCallback(
    ({ forgetAddress = false }: SignOutOptions = {}) => {
      // Also when the session had already ended (a logout answered 401): the person still left.
      if (forgetAddress) setAddressForgotten(true);
      if (queryClient.getQueryData(ME) === null) return;
      // A read of the session still on its way must not sign the user back in when it answers.
      void queryClient.cancelQueries({ queryKey: ME });
      // While the observer above is attached, so RequireAuth re-renders and redirects to /login.
      queryClient.setQueryData(ME, null);
      // Removing a query also cancels its fetch and any retry; the pages unmount with the redirect.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME[0] });
    },
    [queryClient],
  );

  useEffect(() => {
    // A session that ended by itself; the listener is handed the event, not options.
    const unauthorized = () => {
      signOutLocally();
    };
    window.addEventListener("tralala:unauthorized", unauthorized);
    return () => window.removeEventListener("tralala:unauthorized", unauthorized);
  }, [signOutLocally]);

  /** A session begins (or the read finds none): what the last sign-out forgot is kept again. */
  const begin = useCallback(
    (actor: Actor | null) => {
      if (actor) setAddressForgotten(false);
      queryClient.setQueryData(ME, actor);
    },
    [queryClient],
  );

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: begin,
  });

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(),
    onSettled: () => {
      signOutLocally({ forgetAddress: true });
    },
  });

  const login = useCallback(
    (username: string, password: string) => loginMutation.mutateAsync({ username, password }),
    [loginMutation],
  );
  const logout = useCallback(() => logoutMutation.mutateAsync(), [logoutMutation]);
  /** Re-read the session, for flows that sign in outside the login form (an invitation link). */
  const refresh = useCallback(async () => {
    const actor = await fetchActor();
    begin(actor);
    return actor;
  }, [begin]);

  const value = useMemo(
    () => ({
      actor: data ?? null,
      loading: isLoading,
      login,
      logout,
      refresh,
      addressForgotten,
      signOutLocally,
    }),
    [data, isLoading, login, logout, refresh, addressForgotten, signOutLocally],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
