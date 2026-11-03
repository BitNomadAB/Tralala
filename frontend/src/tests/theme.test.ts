import { describe, expect, it } from "vitest";
import { applyTheme, readStoredKit, readStoredTheme, resolveTheme } from "@/themes/theme";

describe("theme resolution", () => {
  it("defaults to dark when nothing is stored", () => {
    localStorage.removeItem("tralala-theme");
    expect(readStoredTheme()).toBe("dark");
  });

  it("honours the stored preference", () => {
    localStorage.setItem("tralala-theme", "light");
    expect(readStoredTheme()).toBe("light");
    localStorage.removeItem("tralala-theme");
  });

  it("resolves system mode from the prefers-color-scheme value", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("defaults the theme kit to CareNomad", () => {
    localStorage.removeItem("tralala-theme-kit");
    expect(readStoredKit()).toBe("carenomad");
  });

  it("honours the stored theme kit", () => {
    localStorage.setItem("tralala-theme-kit", "matchmap");
    expect(readStoredKit()).toBe("matchmap");
    localStorage.setItem("tralala-theme-kit", "classic");
    expect(readStoredKit()).toBe("classic");
    localStorage.setItem("tralala-theme-kit", "nonsense");
    expect(readStoredKit()).toBe("carenomad");
    localStorage.removeItem("tralala-theme-kit");
  });

  it("applies the theme through a data attribute used by CSS variables", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themeKit).toBe("carenomad");
  });

  it("applies the kit alongside the mode", () => {
    applyTheme("light", "matchmap");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.dataset.themeKit).toBe("matchmap");
    applyTheme("dark", "matchmap");
    expect(document.documentElement.dataset.themeKit).toBe("matchmap");
  });
});
