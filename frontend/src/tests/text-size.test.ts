import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");
/** The smallest text the app shows, in CSS pixels: Tailwind's text-xs in this app's scale. */
const FLOOR_PX = 12;

/** The app's own source files with their path in forward slashes, tests left out. */
function sourceFiles(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .map((file) => file.replaceAll("\\", "/"))
    .filter((file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file))
    .filter((file) => !file.startsWith("tests/"));
}

function read(file: string): string {
  return readFileSync(join(SRC, file), "utf8");
}

/** An arbitrary Tailwind text size in pixels, `text-[11px]` or `text-[0.6rem]` (16 px a rem). */
function pixels(value: string, unit: string): number {
  return unit === "px" ? Number(value) : Number(value) * 16;
}

describe("the app's smallest text (WCAG 1.4.4)", () => {
  it("sets no Tailwind text size below 12px in any component", () => {
    const tooSmall = sourceFiles().flatMap((file) =>
      [...read(file).matchAll(/text-\[(\d+(?:\.\d+)?)(px|rem)\]/g)]
        .filter(([, value = "", unit = ""]) => pixels(value, unit) < FLOOR_PX)
        .map(([utility]) => `${file}: ${utility}`),
    );
    expect(tooSmall).toEqual([]);
  });

  it("keeps the scale's smallest step and every size in index.css at 12px or more", () => {
    const css = read("index.css");
    expect(css).toMatch(/--text-xs:\s*12px;/);
    const tooSmall = [...css.matchAll(/font-size:\s*([^;]+);/g)]
      .map(([, value = ""]) => value.trim())
      .filter((value) => {
        // A size relative to its surroundings needs a floor of its own; an absolute one is read.
        if (value.startsWith("max(12px,")) return false;
        const absolute = /^(\d+(?:\.\d+)?)(px|rem)$/.exec(value);
        if (absolute) return pixels(absolute[1] ?? "0", absolute[2] ?? "px") < FLOOR_PX;
        return value.endsWith("em") && Number.parseFloat(value) < 1;
      });
    expect(tooSmall).toEqual([]);
  });
});

/**
 * Text cut off with an ellipsis is lost to anyone who cannot hover (WCAG 1.4.10). Each `truncate`
 * left in the app shows text that is in full somewhere a keyboard reaches; a new one wraps instead
 * (`min-w-0 break-words`) or joins this list with that place named.
 */
const TRUNCATED_ELSEWHERE_IN_FULL: Record<string, string> = {
  // The closed menu's choice; the open list shows every option in full.
  "components/ui/select-menu.tsx": "the option list",
  // The breadcrumb's last crumb; the discussion's heading below it is the whole question.
  "features/discussions/DiscussionPage.tsx": "the discussion heading",
};

describe("text that is cut off (WCAG 1.4.10)", () => {
  it("truncates only where the full text is shown elsewhere", () => {
    const cut = sourceFiles()
      .filter((file) => /\btruncate\b/.test(read(file)))
      .filter((file) => !(file in TRUNCATED_ELSEWHERE_IN_FULL));
    expect(cut).toEqual([]);
  });
});
