/**
 * The rows of "How to format". The help renders each example through `renderMarkdown`, and
 * `src/tests/markdown-field.test.tsx` asserts what every one renders to, so the help can only
 * show what the renderer does.
 */
export interface FormattingExample {
  /** What the row shows, in plain words. */
  title: string;
  /** What a person types. */
  syntax: string;
  /** A sentence under the result, when the syntax needs one. */
  note?: string | undefined;
}

export const FORMATTING_EXAMPLES = {
  bold: { title: "Bold", syntax: "**important**" },
  italic: { title: "Italic", syntax: "*a little emphasis*" },
  inlineCode: { title: "Code in a sentence", syntax: "Open `settings.json` first." },
  heading: {
    title: "A heading",
    syntax: "## Next steps",
    note: "One # is the largest heading, #### the smallest.",
  },
  bulletList: { title: "A bullet list", syntax: "- first\n- second" },
  numberedList: { title: "A numbered list", syntax: "1. first\n2. second" },
  link: {
    title: "A link",
    syntax: "[Example](https://example.com)",
    note: "Links to other sites open in a new tab; only http(s) links become links.",
  },
  webAddress: {
    title: "A web address",
    syntax: "See https://example.com",
    note: "An address on its own becomes a link too.",
  },
  codeBlock: {
    title: "A block of code",
    syntax: "```\nline one\nline two\n```",
    note: "Three backticks on a line of their own before and after the code.",
  },
  paragraphBreak: {
    title: "A new paragraph",
    syntax: "First paragraph.\n\nSecond paragraph.",
    note: "Leave an empty line between them; lines with no empty line between them join up.",
  },
} as const satisfies Record<string, FormattingExample>;

export type FormattingExampleName = keyof typeof FORMATTING_EXAMPLES;
