/**
 * Colour contrast as WCAG 2.2 measures it: the relative luminance of an sRGB colour and the ratio
 * between two of them, which success criteria 1.4.3 (text, 4.5:1) and 1.4.11 (non-text, 3:1) set
 * limits on. Pure maths, so the palette test and the label chip use the same numbers.
 */

/** A colour as its red, green and blue channels, each 0-255. */
export type Rgb = readonly [number, number, number];

export const WHITE: Rgb = [255, 255, 255];
export const BLACK: Rgb = [0, 0, 0];

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

function channel(digits: string, start: number): number {
  return Number.parseInt(digits.slice(start, start + 2), 16);
}

/** Reads `#rgb` or `#rrggbb`; anything else (a colour name, `rgb(...)`, a typo) is null. */
export function parseHex(value: string): Rgb | null {
  const digits = HEX.exec(value.trim())?.[1];
  if (digits === undefined) return null;
  const full = digits.length === 3 ? digits.replace(/./g, (digit) => digit.repeat(2)) : digits;
  return [channel(full, 0), channel(full, 2), channel(full, 4)];
}

/** `#rrggbb`, each channel rounded and kept inside 0-255. */
export function toHex(rgb: Rgb): string {
  const parts = rgb.map((value) =>
    Math.round(Math.min(255, Math.max(0, value)))
      .toString(16)
      .padStart(2, "0"),
  );
  return `#${parts.join("")}`;
}

function linear(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance: 0 for black, 1 for white. */
export function relativeLuminance([red, green, blue]: Rgb): number {
  return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
}

/** WCAG contrast ratio, from 1 (the same luminance) to 21 (black on white); order does not matter. */
export function contrastRatio(first: Rgb, second: Rgb): number {
  const a = relativeLuminance(first);
  const b = relativeLuminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * `colour` painted at `share` (0-1) opacity over `ground`. This is what
 * `color-mix(in srgb, colour N%, transparent)` shows on top of a ground, with share N/100.
 */
export function mixOver(colour: Rgb, ground: Rgb, share: number): Rgb {
  const mix = (top: number, bottom: number) => top * share + bottom * (1 - share);
  return [mix(colour[0], ground[0]), mix(colour[1], ground[1]), mix(colour[2], ground[2])];
}

function rounded(rgb: Rgb): Rgb {
  return [Math.round(rgb[0]), Math.round(rgb[1]), Math.round(rgb[2])];
}

/**
 * The colour nearest to `colour` that reaches `minimum` contrast against `ground`: the colour
 * itself when it already does, otherwise mixed a step at a time towards white on a dark ground or
 * black on a light one, so it keeps as much of its own hue as the limit allows. When even white or
 * black falls short, that is the answer, as no colour does better.
 */
export function readableOn(colour: Rgb, ground: Rgb, minimum: number): Rgb {
  const towards = contrastRatio(WHITE, ground) >= contrastRatio(BLACK, ground) ? WHITE : BLACK;
  for (let step = 0; step <= 100; step += 1) {
    const candidate = rounded(mixOver(towards, colour, step / 100));
    if (contrastRatio(candidate, ground) >= minimum) return candidate;
  }
  return towards;
}
