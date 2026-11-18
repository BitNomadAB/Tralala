import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { contrastRatio, mixOver, parseHex, relativeLuminance, type Rgb } from "@/lib/contrast";
import { LABEL_GROUNDS, TEXT_CONTRAST } from "@/lib/labelInk";

/** WCAG 1.4.11: a control's edge and the focus ring need 3:1 against what is next to them. */
const NON_TEXT_CONTRAST = 3;

// Paths from this file; jsdom replaces URL, which node:fs then refuses as a file URL.
const css = readFileSync(join(import.meta.dirname, "../index.css"), "utf8");
const badgeSource = readFileSync(join(import.meta.dirname, "../components/ui/badge.tsx"), "utf8");

/** The kit blocks of index.css, by the selector that opens them. */
const BLOCKS = {
  base: ":root",
  baseLight: ':root[data-theme="light"]',
  matchmap: ':root[data-theme-kit="matchmap"]',
  matchmapLight: ':root[data-theme-kit="matchmap"][data-theme="light"]',
  classic: ':root[data-theme-kit="classic"]',
  classicLight: ':root[data-theme-kit="classic"][data-theme="light"]',
} as const;

type Block = keyof typeof BLOCKS;

/**
 * Each palette as the browser builds it on <html>: the blocks that match, in the order the cascade
 * applies them (equal specificity goes by source order, so a kit's dark block overrides CareNomad's
 * light one, and the kit's own light block comes last).
 */
const PALETTES: Record<string, readonly Block[]> = {
  "CareNomad dark": ["base"],
  "CareNomad light": ["base", "baseLight"],
  "MatchMap dark": ["base", "matchmap"],
  "MatchMap light": ["base", "baseLight", "matchmap", "matchmapLight"],
  "Classic dark": ["base", "classic"],
  "Classic light": ["base", "baseLight", "classic", "classicLight"],
};

/** The palettes held to WCAG 2.2 AA contrast. */
const CHECKED = ["Classic dark", "Classic light"];

/**
 * Deliberate exceptions: the product owner decided on 2026-11-18 that only Classic is held to
 * WCAG 2.2 AA contrast, and that CareNomad and MatchMap keep exactly the look they have; their
 * contrast is a design choice. They are held only to that: the tokens added for Classic reproduce
 * what they drew before.
 */
const EXCEPTIONS = ["CareNomad dark", "CareNomad light", "MatchMap dark", "MatchMap light"];

const GROUNDS = ["background", "surface", "surface-raised"] as const;
const TEXT = [
  "foreground",
  "muted-foreground",
  "foreground-faint",
  "primary",
  "accent",
  "destructive",
  "success",
  "warning",
] as const;
/** Button text and the fill it sits on. */
const BUTTONS = [
  ["primary-foreground", "primary"],
  ["destructive-foreground", "destructive"],
] as const;

function declarations(block: Block): Map<string, string> {
  const opening = `\n${BLOCKS[block]} {\n`;
  const start = css.indexOf(opening);
  if (start < 0) throw new Error(`index.css has no block ${BLOCKS[block]}`);
  const body = css.slice(start + opening.length, css.indexOf("\n}", start));
  const tokens = new Map<string, string>();
  for (const [, name, value] of body.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    if (name !== undefined && value !== undefined) tokens.set(name, value.trim());
  }
  return tokens;
}

function palette(name: string): Map<string, string> {
  const blocks = PALETTES[name];
  if (!blocks) throw new Error(`no palette ${name}`);
  return new Map(blocks.flatMap((block) => [...declarations(block)]));
}

/** A token's value with `var(--other)` followed to the end, as the browser computes it. */
function resolved(tokens: Map<string, string>, name: string): string {
  const value = tokens.get(name);
  if (value === undefined) throw new Error(`--${name} is not defined`);
  const reference = /^var\(--([\w-]+)\)$/.exec(value)?.[1];
  return reference === undefined ? value : resolved(tokens, reference);
}

function colour(tokens: Map<string, string>, name: string): Rgb {
  const value = resolved(tokens, name);
  const rgb = parseHex(value);
  if (!rgb) throw new Error(`--${name} is ${value}, not a hex colour`);
  return rgb;
}

/** The tinted badge tones of badge.tsx: the tint token, its share and the text token on it. */
function badgeTones(): { tint: string; share: number; text: string }[] {
  const pattern =
    /bg-\[color-mix\(in_srgb,var\(--([\w-]+)\)_(\d+)%,transparent\)\] text-\[var\(--([\w-]+)\)\]/g;
  return [...badgeSource.matchAll(pattern)].map(([, tint = "", share = "", text = ""]) => ({
    tint,
    share: Number(share) / 100,
    text,
  }));
}

/** One line per pair below its limit, with the ratio, so a failure says what to fix. */
function shortfall(label: string, ratio: number, limit: number): string[] {
  return ratio >= limit ? [] : [`${label}: ${ratio.toFixed(2)}:1, needs ${limit}:1`];
}

describe("the palettes", () => {
  it("are each either held to WCAG AA or listed as a deliberate exception", () => {
    expect([...CHECKED, ...EXCEPTIONS].sort()).toEqual(Object.keys(PALETTES).sort());
  });

  it("finds the four tinted badge tones in badge.tsx", () => {
    expect(badgeTones().map((tone) => tone.text)).toEqual([
      "primary",
      "success",
      "warning",
      "destructive",
    ]);
  });
});

describe.each(CHECKED)("%s", (name) => {
  const tokens = palette(name);

  it("writes every text colour at 4.5:1 on the background and both surfaces", () => {
    const failures = TEXT.flatMap((text) =>
      GROUNDS.flatMap((ground) =>
        shortfall(
          `--${text} on --${ground}`,
          contrastRatio(colour(tokens, text), colour(tokens, ground)),
          TEXT_CONTRAST,
        ),
      ),
    );
    expect(failures).toEqual([]);
  });

  it("writes button text at 4.5:1 on the primary and the danger fill", () => {
    const failures = BUTTONS.flatMap(([text, fill]) =>
      shortfall(
        `--${text} on --${fill}`,
        contrastRatio(colour(tokens, text), colour(tokens, fill)),
        TEXT_CONTRAST,
      ),
    );
    expect(failures).toEqual([]);
  });

  it("writes each tinted badge's text at 4.5:1 on its tint, wherever the badge sits", () => {
    const failures = badgeTones().flatMap(({ tint, share, text }) =>
      GROUNDS.flatMap((ground) => {
        const fill = mixOver(colour(tokens, tint), colour(tokens, ground), share);
        return shortfall(
          `badge --${text} on ${share * 100}% --${tint} over --${ground}`,
          contrastRatio(colour(tokens, text), fill),
          TEXT_CONTRAST,
        );
      }),
    );
    expect(failures).toEqual([]);
  });

  it("draws a field's edge at 3:1 against the field and against what is around it", () => {
    const edge = colour(tokens, "field-border");
    const failures = GROUNDS.flatMap((ground) =>
      shortfall(
        `--field-border against --${ground}`,
        contrastRatio(edge, colour(tokens, ground)),
        NON_TEXT_CONTRAST,
      ),
    );
    expect(failures).toEqual([]);
  });

  it("draws the focus ring at 3:1 against the background and both surfaces", () => {
    const ring = colour(tokens, "ring");
    const failures = GROUNDS.flatMap((ground) =>
      shortfall(
        `--ring against --${ground}`,
        contrastRatio(ring, colour(tokens, ground)),
        NON_TEXT_CONTRAST,
      ),
    );
    expect(failures).toEqual([]);
  });
});

describe.each(EXCEPTIONS)("%s, a deliberate exception", (name) => {
  const tokens = palette(name);

  it("keeps white text on the danger button, as it had before the token", () => {
    expect(resolved(tokens, "destructive-foreground")).toBe("#ffffff");
  });

  it("keeps a field's edge in the border colour, as it had before the token", () => {
    expect(resolved(tokens, "field-border")).toBe(resolved(tokens, "border"));
  });
});

describe("the label chip's grounds", () => {
  // labelInk() makes a label's colour readable against LABEL_GROUNDS; that holds on a kit's
  // grounds only while none of them is harder than these.
  it.each(Object.keys(PALETTES))("are at least as hard as every ground of %s", (name) => {
    const tokens = palette(name);
    const dark = name.endsWith("dark");
    const limit = relativeLuminance(dark ? LABEL_GROUNDS.dark : LABEL_GROUNDS.light);
    const harder = GROUNDS.filter((ground) => {
      const luminance = relativeLuminance(colour(tokens, ground));
      return dark ? luminance > limit : luminance < limit;
    });
    expect(harder).toEqual([]);
  });
});
