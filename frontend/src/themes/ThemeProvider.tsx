import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/features/auth/AuthProvider";
import { api } from "@/lib/api";

export type ThemeMode = "dark" | "light" | "system";
export type ThemeKit = "carenomad" | "matchmap" | "classic";

export const THEME_KITS: { value: ThemeKit; label: string; description: string }[] = [
  {
    value: "carenomad",
    label: "CareNomad",
    description: "Midnight navy with periwinkle light",
  },
  {
    value: "matchmap",
    label: "MatchMap",
    description: "Ink-blue night with ember orange",
  },
  {
    value: "classic",
    label: "Classic",
    description: "The original flat palette, no ambient motion",
  },
];

const STORAGE_KEY = "tralala-theme";
const KIT_KEY = "tralala-theme-kit";

interface ThemeContextValue {
  mode: ThemeMode;
  kit: ThemeKit;
  resolved: "dark" | "light";
  setMode: (mode: ThemeMode) => void;
  setKit: (kit: ThemeKit) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function readStoredTheme(): ThemeMode {
  const stored = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "dark";
}

export function readStoredKit(): ThemeKit {
  const stored = typeof localStorage !== "undefined" ? localStorage.getItem(KIT_KEY) : null;
  return stored === "matchmap" || stored === "carenomad" || stored === "classic"
    ? stored
    : "carenomad";
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): "dark" | "light" {
  if (mode === "system") return prefersDark ? "dark" : "light";
  return mode;
}

export function applyTheme(theme: "dark" | "light", kit: ThemeKit = "carenomad"): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themeKit = kit;
}

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
    const listener = (event: MediaQueryListEvent) => setPrefersDark(event.matches);
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, []);

  const resolved = resolveTheme(mode, prefersDark);

  useEffect(() => {
    applyTheme(resolved, kit);
    localStorage.setItem(STORAGE_KEY, mode);
    localStorage.setItem(KIT_KEY, kit);
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

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
