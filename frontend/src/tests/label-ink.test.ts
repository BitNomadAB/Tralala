import { describe, expect, it } from "vitest";
import { contrastRatio, parseHex } from "@/lib/contrast";
import { LABEL_GROUNDS, labelInk, TEXT_CONTRAST } from "@/lib/labelInk";

function contrastOn(ground: keyof typeof LABEL_GROUNDS, hex: string): number {
  const rgb = parseHex(hex);
  if (!rgb) throw new Error(`not hex: ${hex}`);
  return contrastRatio(rgb, LABEL_GROUNDS[ground]);
}

describe("labelInk", () => {
  it("makes the default label colour readable in a dark and in a light palette", () => {
    // #64748b is the colour a label gets when nobody picks one.
    const ink = labelInk("#64748b");
    if (!ink) throw new Error("no ink");
    expect(contrastOn("dark", "#64748b")).toBeLessThan(TEXT_CONTRAST);
    expect(contrastOn("light", "#64748b")).toBeLessThan(TEXT_CONTRAST);
    expect(contrastOn("dark", ink.dark)).toBeGreaterThanOrEqual(TEXT_CONTRAST);
    expect(contrastOn("light", ink.light)).toBeGreaterThanOrEqual(TEXT_CONTRAST);
  });

  it("keeps a colour exactly where it already reads, and moves it only in the mode it does not", () => {
    expect(labelInk("#FFFFFF")?.dark).toBe("#ffffff");
    expect(labelInk("#000000")?.light).toBe("#000000");
    const white = labelInk("#ffffff");
    if (!white) throw new Error("no ink");
    expect(white.light).not.toBe("#ffffff");
    expect(contrastOn("light", white.light)).toBeGreaterThanOrEqual(TEXT_CONTRAST);
  });

  it("reads a short hex colour too", () => {
    expect(labelInk("#fff")?.dark).toBe("#ffffff");
  });

  it("has no ink for a colour that is not hex, so the chip falls back to the theme's text", () => {
    expect(labelInk("red")).toBeNull();
    expect(labelInk("")).toBeNull();
  });
});
