import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/features/auth/useAuth";
import { api } from "@/lib/api";
import {
  applyTheme,
  readStoredKit,
  readStoredTheme,
  resolveTheme,
  storeTheme,
  type ThemeKit,
  type ThemeMode,
} from "./theme";
import { ThemeContext } from "./useTheme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const { actor } = useAuth();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ThemeMode>(() => readStoredTheme());
  const [kit, setKit] = useState<ThemeKit>(() => readStoredKit());
  const appliedActor = useRef<string | null>(null);
  const [prefersDark, setPrefersDark] = useState<boolean>(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : true,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event: MediaQueryListEvent) => {
      setPrefersDark(event.matches);
    };
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);

  const resolved = resolveTheme(mode, prefersDark);

  useEffect(() => {
    applyTheme(resolved, kit);
    storeTheme(mode, kit);
  }, [mode, kit, resolved]);

  // The account's stored preference wins over this browser's cache once it loads.
  useEffect(() => {
    if (!actor) {
      appliedActor.current = null;
      return;
    }
    if (appliedActor.current === actor.id) return;
    appliedActor.current = actor.id;
    const preferences = actor.preferences;
    // A fresh account starts from the default kit rather than inheriting this browser's cache.
    setMode(preferences?.theme_mode ?? "dark");
    setKit(preferences?.theme_kit ?? "carenomad");
  }, [actor]);

  const persist = useCallback(
    (nextMode: ThemeMode, nextKit: ThemeKit) => {
      if (!actor) return;
      queryClient.setQueryData(["me"], {
        ...actor,
        preferences: { theme_mode: nextMode, theme_kit: nextKit },
      });
      void api
        .updatePreferences({ theme_mode: nextMode, theme_kit: nextKit })
        .catch(() => undefined);
    },
    [actor, queryClient],
  );

  const updateMode = useCallback(
    (next: ThemeMode) => {
      setMode(next);
      persist(next, kit);
    },
    [kit, persist],
  );
  const updateKit = useCallback(
    (next: ThemeKit) => {
      setKit(next);
      persist(mode, next);
    },
    [mode, persist],
  );
  const value = useMemo(
    () => ({ mode, kit, resolved, setMode: updateMode, setKit: updateKit }),
    [mode, kit, resolved, updateMode, updateKit],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
