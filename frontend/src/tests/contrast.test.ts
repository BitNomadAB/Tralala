import { describe, expect, it } from "vitest";
import {
  BLACK,
  WHITE,
  contrastRatio,
  mixOver,
  parseHex,
  readableOn,
  relativeLuminance,
  toHex,
  type Rgb,
} from "@/lib/contrast";

describe("WCAG contrast maths", () => {
  it("gives white a luminance of 1 and black 0", () => {
    expect(relativeLuminance(WHITE)).toBe(1);
    expect(relativeLuminance(BLACK)).toBe(0);
  });

  it("measures black on white as 21:1 and a colour on itself as 1:1, in either order", () => {
    expect(contrastRatio(BLACK, WHITE)).toBe(21);
    expect(contrastRatio(WHITE, BLACK)).toBe(21);
    const grey: Rgb = [0x76, 0x76, 0x76];
    expect(contrastRatio(grey, grey)).toBe(1);
  });

  it("matches WCAG's own example: #767676 on white is the lightest grey that passes 4.5:1", () => {
    expect(contrastRatio([0x76, 0x76, 0x76], WHITE)).toBeCloseTo(4.54, 2);
    expect(contrastRatio([0x77, 0x77, 0x77], WHITE)).toBeLessThan(4.5);
  });

  it("reads #rgb and #rrggbb in any case, with surrounding space", () => {
    expect(parseHex("#fff")).toEqual([255, 255, 255]);
    expect(parseHex("#1A2b3C")).toEqual([0x1a, 0x2b, 0x3c]);
    expect(parseHex("  #0a1628 ")).toEqual([0x0a, 0x16, 0x28]);
  });

  it("refuses what is not a hex colour", () => {
    for (const value of ["red", "", "#12", "#12345", "#1234567", "0a1628", "rgb(0, 0, 0)"]) {
      expect(parseHex(value)).toBeNull();
    }
  });

  it("writes #rrggbb, rounding and clamping each channel", () => {
    expect(toHex([255, 0, 127.6])).toBe("#ff0080");
    expect(toHex([300, -5, 9])).toBe("#ff0009");
  });

  it("paints a colour at a share of opacity over a ground, as color-mix with transparent does", () => {
    const tint = mixOver(WHITE, BLACK, 0.18).map((value) => Math.round(value * 10) / 10);
    expect(tint).toEqual([45.9, 45.9, 45.9]);
    const colour: Rgb = [10, 200, 30];
    const ground: Rgb = [250, 0, 100];
    expect(mixOver(colour, ground, 1)).toEqual(colour);
    expect(mixOver(colour, ground, 0)).toEqual(ground);
  });
});

describe("readableOn", () => {
  const darkGround: Rgb = [0x16, 0x23, 0x3a];
  const lightGround: Rgb = [0xfd, 0xea, 0xe3];
  const slate: Rgb = [0x64, 0x74, 0x8b];

  it("keeps a colour that already reaches the limit", () => {
    const sky: Rgb = [0x7b, 0xa7, 0xff];
    expect(contrastRatio(sky, darkGround)).toBeGreaterThan(4.5);
    expect(readableOn(sky, darkGround, 4.5)).toEqual(sky);
  });

  it("lightens a colour on a dark ground only as far as the limit needs", () => {
    expect(contrastRatio(slate, darkGround)).toBeLessThan(4.5);
    const ink = readableOn(slate, darkGround, 4.5);
    expect(contrastRatio(ink, darkGround)).toBeGreaterThanOrEqual(4.5);
    expect(relativeLuminance(ink)).toBeGreaterThan(relativeLuminance(slate));
    // Still a tint of the colour, not plain white.
    expect(ink).not.toEqual(WHITE);
    expect(ink[2]).toBeGreaterThan(ink[0]);
  });

  it("darkens a colour on a light ground only as far as the limit needs", () => {
    expect(contrastRatio(slate, lightGround)).toBeLessThan(4.5);
    const ink = readableOn(slate, lightGround, 4.5);
    expect(contrastRatio(ink, lightGround)).toBeGreaterThanOrEqual(4.5);
    expect(relativeLuminance(ink)).toBeLessThan(relativeLuminance(slate));
    expect(ink).not.toEqual(BLACK);
  });

  it("passes a colour darker than a dark ground on the way to white", () => {
    const ink = readableOn(BLACK, darkGround, 4.5);
    expect(contrastRatio(ink, darkGround)).toBeGreaterThanOrEqual(4.5);
    expect(relativeLuminance(ink)).toBeGreaterThan(relativeLuminance(darkGround));
  });

  it("answers white or black when no colour reaches the limit", () => {
    expect(readableOn(slate, darkGround, 30)).toEqual(WHITE);
    expect(readableOn(slate, lightGround, 30)).toEqual(BLACK);
  });
});
