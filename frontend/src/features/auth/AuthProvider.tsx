import { createContext, useCallback, useContext, useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import type { Actor } from "@/lib/types";

interface AuthContextValue {
  actor: Actor | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Actor>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

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
    queryKey: ["me"],
    queryFn: fetchActor,
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    const handler = () => {
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
    };
    window.addEventListener("tralala:unauthorized", handler);
    return () => window.removeEventListener("tralala:unauthorized", handler);
  }, [queryClient]);

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: (actor) => queryClient.setQueryData(["me"], actor),
  });

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(),
    onSettled: () => {
      queryClient.setQueryData(["me"], null);
      queryClient.clear();
    },
  });

  const login = useCallback(
    (username: string, password: string) => loginMutation.mutateAsync({ username, password }),
    [loginMutation],
  );
  const logout = useCallback(() => logoutMutation.mutateAsync(), [logoutMutation]);

  const value = useMemo(
    () => ({ actor: data ?? null, loading: isLoading, login, logout }),
    [data, isLoading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
