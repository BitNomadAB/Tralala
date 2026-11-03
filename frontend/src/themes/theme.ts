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

/** This browser's cache of the choice, read back by `readStoredTheme` and `readStoredKit`. */
export function storeTheme(mode: ThemeMode, kit: ThemeKit): void {
  localStorage.setItem(STORAGE_KEY, mode);
  localStorage.setItem(KIT_KEY, kit);
}

export function resolveTheme(mode: ThemeMode, prefersDark: boolean): "dark" | "light" {
  if (mode === "system") return prefersDark ? "dark" : "light";
  return mode;
}

export function applyTheme(theme: "dark" | "light", kit: ThemeKit = "carenomad"): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themeKit = kit;
}
