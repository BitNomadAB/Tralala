import { useRef, useState, type KeyboardEvent } from "react";

/**
 * The title read first and edited on request: `start` turns the heading into a field holding the
 * title, Enter (or leaving the field) saves a changed, non-empty title through `onSave`, and
 * Escape puts the heading back as it was. Saving closes the field at once; when the server refuses,
 * the refetched card shows the title it holds.
 */
export function useTitleEdit({
  title,
  onSave,
}: {
  title: string;
  onSave: (title: string) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  // Set while the field is open, so a blur that follows Enter or Escape saves nothing twice.
  const open = useRef(false);

  function start() {
    open.current = true;
    setDraft(title);
  }

  function cancel() {
    open.current = false;
    setDraft(null);
  }

  function save(value: string) {
    if (!open.current) return;
    open.current = false;
    setDraft(null);
    const next = value.trim();
    if (next && next !== title) onSave(next);
  }

  return {
    editing: draft !== null,
    draft: draft ?? title,
    start,
    change: (value: string) => {
      setDraft(value);
    },
    cancel,
    save,
    onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        save(event.currentTarget.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancel();
      }
    },
  };
}
