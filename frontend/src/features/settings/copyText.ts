import { clipboard } from "@/lib/utils";

/** What a person does instead when the browser will not copy for them. */
export const COPY_BY_HAND = "Select the text and press Ctrl+C.";

/**
 * Copies `text` to the clipboard and says whether it did. The browser has no clipboard outside a
 * secure context (a server reached over plain HTTP on a private network), and may refuse a write,
 * so neither is taken for a success.
 */
export async function copyText(text: string): Promise<boolean> {
  const target = clipboard();
  if (!target) return false;
  try {
    await target.writeText(text);
    return true;
  } catch {
    return false;
  }
}
