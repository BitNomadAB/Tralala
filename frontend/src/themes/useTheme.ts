import { createContext, useContext } from "react";
import type { ThemeKit, ThemeMode } from "./theme";

export interface ThemeContextValue {
  mode: ThemeMode;
  kit: ThemeKit;
  resolved: "dark" | "light";
  setMode: (mode: ThemeMode) => void;
  setKit: (kit: ThemeKit) => void;
}

/** Shared by `ThemeProvider` and `useTheme`; a component file exports only components. */
export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
