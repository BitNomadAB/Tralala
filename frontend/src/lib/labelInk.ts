import { parseHex, readableOn, toHex, type Rgb } from "./contrast";

/** WCAG 1.4.3: normal-size text needs 4.5:1 against what it is drawn on. */
export const TEXT_CONTRAST = 4.5;

/**
 * The hardest grounds a label chip is drawn on: the lightest background, surface or raised surface
 * of any dark palette (CareNomad's raised surface, #16233a) and the darkest of any light one
 * (MatchMap's raised surface, #fdeae3). Contrast with text lighter than a dark ground only grows as
 * the ground gets darker, and the other way round, so a text colour that passes here passes on
 * every ground of that mode. The palette test holds every kit in index.css to these two.
 */
export const LABEL_GROUNDS: { dark: Rgb; light: Rgb } = {
  dark: [0x16, 0x23, 0x3a],
  light: [0xfd, 0xea, 0xe3],
};

/** A label's text colour for a dark palette and for a light one, both `#rrggbb`. */
export interface LabelInk {
  dark: string;
  light: string;
}

/**
 * A label's own colour, moved only as far as it must to be readable as text in a dark and in a
 * light palette. A label's colour is what a person chose, not the theme's, so it holds in every
 * kit. Null for a colour that is not hex; the chip then writes its name in the theme's text colour.
 */
export function labelInk(colour: string): LabelInk | null {
  const rgb = parseHex(colour);
  if (!rgb) return null;
  return {
    dark: toHex(readableOn(rgb, LABEL_GROUNDS.dark, TEXT_CONTRAST)),
    light: toHex(readableOn(rgb, LABEL_GROUNDS.light, TEXT_CONTRAST)),
  };
}
