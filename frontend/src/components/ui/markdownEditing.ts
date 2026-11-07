/**
 * The text edits behind the Markdown field's shortcuts, as pure functions of the text and the
 * selection, so each can be tested without a browser.
 */

/** The text after an edit, and the selection to put back. */
export interface MarkdownEdit {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

/** What a shortcut needs from a key event. */
export interface ShortcutKey {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

/** Stands in the brackets of a link until a person types or pastes the address over it. */
export const URL_PLACEHOLDER = "url";

/** One http(s) address and nothing else. */
const SINGLE_URL = /^https?:\/\/[^\s<>]+$/i;

/** Puts `marker` on both sides of the selection, which stays selected inside the markers. */
export function wrapSelection(
  value: string,
  start: number,
  end: number,
  marker: string,
): MarkdownEdit {
  const selected = value.slice(start, end);
  return {
    value: `${value.slice(0, start)}${marker}${selected}${marker}${value.slice(end)}`,
    selectionStart: start + marker.length,
    selectionEnd: end + marker.length,
  };
}

/**
 * Makes `[selection](url)` with the placeholder selected, so the address typed or pasted next
 * replaces it. On an empty selection it inserts `[](url)` with the caret between the brackets.
 */
export function linkSelection(value: string, start: number, end: number): MarkdownEdit {
  const selected = value.slice(start, end);
  const link = `[${selected}](${URL_PLACEHOLDER})`;
  const next = `${value.slice(0, start)}${link}${value.slice(end)}`;
  if (selected === "") return { value: next, selectionStart: start + 1, selectionEnd: start + 1 };
  const placeholder = start + selected.length + 3;
  return {
    value: next,
    selectionStart: placeholder,
    selectionEnd: placeholder + URL_PLACEHOLDER.length,
  };
}

/**
 * Pasting one http(s) address over selected text makes `[text](address)`, with the caret after it.
 * Anything else is an ordinary paste (null): an empty selection, other text, or a selection that
 * already sits in a link's brackets, such as the placeholder `linkSelection` leaves.
 */
export function pasteLink(
  value: string,
  start: number,
  end: number,
  pasted: string,
): MarkdownEdit | null {
  const url = pasted.trim();
  if (start === end || !SINGLE_URL.test(url) || value.slice(0, start).endsWith("](")) return null;
  const link = `[${value.slice(start, end)}](${url})`;
  const caret = start + link.length;
  return {
    value: `${value.slice(0, start)}${link}${value.slice(end)}`,
    selectionStart: caret,
    selectionEnd: caret,
  };
}

/** Ctrl/Cmd+B bold, Ctrl/Cmd+I italic, Ctrl/Cmd+K link; null for every other key. */
export function shortcutEdit(
  event: ShortcutKey,
  value: string,
  start: number,
  end: number,
): MarkdownEdit | null {
  if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey) return null;
  switch (event.key.toLowerCase()) {
    case "b":
      return wrapSelection(value, start, end, "**");
    case "i":
      return wrapSelection(value, start, end, "*");
    case "k":
      return linkSelection(value, start, end);
    default:
      return null;
  }
}
