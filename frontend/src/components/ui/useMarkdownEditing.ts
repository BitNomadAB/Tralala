import {
  useLayoutEffect,
  useRef,
  type ClipboardEvent,
  type KeyboardEvent,
  type RefObject,
} from "react";
import { pasteLink, shortcutEdit, type MarkdownEdit } from "./markdownEditing";

/**
 * Connects the Markdown shortcuts to a controlled textarea: an edit replaces the value through
 * `onChange`, and the selection it names is put back once React has rendered the new value.
 */
export function useMarkdownEditing(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  onChange: (value: string) => void,
) {
  const pending = useRef<{ start: number; end: number } | null>(null);

  useLayoutEffect(() => {
    const selection = pending.current;
    const field = ref.current;
    if (!selection || !field) return;
    pending.current = null;
    field.setSelectionRange(selection.start, selection.end);
  }, [ref, value]);

  function apply(edit: MarkdownEdit) {
    pending.current = { start: edit.selectionStart, end: edit.selectionEnd };
    onChange(edit.value);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const field = event.currentTarget;
    const edit = shortcutEdit(event, field.value, field.selectionStart, field.selectionEnd);
    if (!edit) return;
    event.preventDefault();
    apply(edit);
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const field = event.currentTarget;
    const pasted = event.clipboardData.getData("text/plain");
    const edit = pasteLink(field.value, field.selectionStart, field.selectionEnd, pasted);
    if (!edit) return;
    event.preventDefault();
    apply(edit);
  }

  return { onKeyDown, onPaste };
}
