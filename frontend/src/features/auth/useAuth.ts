import { createContext, useContext } from "react";
import type { Actor } from "@/lib/types";

/** How `signOutLocally` ends the session in this tab. */
export interface SignOutOptions {
  /**
   * The person signed out themselves (Sign out, a password change), so the next sign-in starts on
   * the dashboard instead of the page they left. A session that ended by itself (a 401) keeps it.
   */
  forgetAddress?: boolean;
}

export interface AuthContextValue {
  actor: Actor | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Actor>;
  /**
   * Asks the server to end the session and signs out in this tab whatever it answers. It never
   * rejects: a session that had already ended, a server error or a lost network still sign out.
   */
  logout: () => Promise<void>;
  refresh: () => Promise<Actor | null>;
  /**
   * The person signed out themselves and nobody has signed in since: the login page then drops the
   * address it was sent from, so the next sign-in opens the dashboard.
   */
  addressForgotten: boolean;
  /**
   * Forget the session in this tab, so the login page shows, without asking the server. Logout, a
   * password change and every 401 end here.
   */
  signOutLocally: (options?: SignOutOptions) => void;
}

/** Shared by `AuthProvider` and `useAuth`; a component file exports only components. */
export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
