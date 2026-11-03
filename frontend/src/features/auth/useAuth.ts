import { createContext, useContext } from "react";
import type { Actor } from "@/lib/types";

export interface AuthContextValue {
  actor: Actor | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Actor>;
  logout: () => Promise<void>;
  refresh: () => Promise<Actor | null>;
  /**
   * Forget the session in this tab, so the login page shows, without asking the server. Logout, a
   * password change and every 401 end here.
   */
  signOutLocally: () => void;
}

/** Shared by `AuthProvider` and `useAuth`; a component file exports only components. */
export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
