import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoopPlanTabs } from "@/features/loops/LoopPlanTabs";

const SRC = join(import.meta.dirname, "..");

/** The app's own source files, tests left out. */
function sourceFiles(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .filter((file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file))
    .filter((file) => !file.startsWith("tests"));
}

describe("the app's own motion under reduced motion (WCAG 2.2.2)", () => {
  it("runs every Tailwind animation only where motion is welcome", () => {
    const unguarded = sourceFiles().flatMap((file) => {
      const text = readFileSync(join(SRC, file), "utf8");
      return [...text.matchAll(/(?:[\w-]+:)*animate-(?!none\b)[a-z-]+/g)]
        .map(([utility]) => utility)
        .filter((utility) => !utility.startsWith("motion-safe:"))
        .map((utility) => `${file}: ${utility}`);
    });
    expect(unguarded).toEqual([]);
  });

  it("animates nothing in index.css but the theme kits' ambient layer", () => {
    // The ambient layer is CareNomad's and MatchMap's by the 2026-11-18 decision and has its own
    // reduced-motion rule; anything else that moves belongs behind motion-safe.
    const css = readFileSync(join(SRC, "index.css"), "utf8");
    const animated = [...css.matchAll(/([^{}]+)\{[^{}]*\banimation:\s*([^;]+);/g)]
      .filter(([, , value = ""]) => value.trim() !== "none")
      .map(([, selector = ""]) => selector.trim())
      .filter((selector) => !selector.includes(".ambient"));
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(animated).toEqual([]);
  });

  it("shows a running generation as a steady ring and its text, the pulse and glow motion-safe", () => {
    render(
      <LoopPlanTabs
        tab="analysis"
        onTabChange={() => undefined}
        technical={false}
        onToggleTechnical={() => undefined}
        agentId=""
        onAgentChange={() => undefined}
        candidates={{ agents: [], restrictedToBoard: false }}
        savedAgentName={undefined}
        agentLocked
        generating
        generateDisabled
        onGenerate={() => undefined}
      />,
    );
    const button = screen.getByRole("button", { name: /Generating…/ });
    expect(button).toHaveClass(
      "ring-2",
      "ring-[var(--primary)]",
      "motion-safe:animate-pulse",
      "motion-safe:shadow-[0_0_22px_3px_var(--primary)]",
    );
    expect(button).not.toHaveClass("animate-pulse");
    expect(button).not.toHaveClass("shadow-[0_0_22px_3px_var(--primary)]");
  });
});
