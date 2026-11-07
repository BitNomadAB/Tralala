import { useRef, type KeyboardEvent } from "react";
import { renderMarkdown, type MarkdownOptions } from "@/lib/markdown";
import { cn } from "@/lib/utils";
import { Textarea } from "./input";
import { MarkdownHelp } from "./markdown-help";
import { useMarkdownEditing } from "./useMarkdownEditing";

const TABS = [
  { preview: false, label: "Write" },
  { preview: true, label: "Preview" },
] as const;

/**
 * Write and Preview tabs (WAI-ARIA tabs, activated by the arrow keys, Home and End). The owner
 * keeps which one is chosen, so the choice survives as long as the owner does.
 */
function MarkdownTabs({
  id,
  title,
  preview,
  onPreviewChange,
}: {
  id: string;
  title: string;
  preview: boolean;
  onPreviewChange: (preview: boolean) => void;
}) {
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  function choose(next: boolean) {
    onPreviewChange(next);
    tabs.current[next ? 1 : 0]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const next =
      event.key === "ArrowLeft" || event.key === "ArrowRight"
        ? !preview
        : event.key === "Home"
          ? false
          : event.key === "End"
            ? true
            : null;
    if (next === null) return;
    event.preventDefault();
    choose(next);
  }

  return (
    <div role="tablist" aria-label={title} className="flex gap-1">
      {TABS.map((tab, index) => {
        const selected = tab.preview === preview;
        return (
          <button
            key={tab.label}
            ref={(element) => {
              tabs.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${tab.label.toLowerCase()}`}
            aria-selected={selected}
            aria-controls={`${id}-panel-${tab.label.toLowerCase()}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onPreviewChange(tab.preview)}
            onKeyDown={onKeyDown}
            className={cn(
              "h-8 rounded-lg px-2.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]",
              selected
                ? "border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--foreground)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * A Markdown text field: Write (the textarea, with Ctrl/Cmd+B, I and K and paste-a-link), Preview
 * (the same renderer the text is shown with) and "How to format" under both. Markdown is what is
 * stored; nothing here produces HTML.
 */
export function MarkdownField({
  id,
  title,
  label,
  value,
  onChange,
  preview,
  onPreviewChange,
  placeholder,
  ticketHref,
}: {
  /** The textarea's id; the tabs and panels derive theirs from it. */
  id: string;
  /** The heading shown above the field, which also names the tabs. */
  title: string;
  /** The textarea's accessible name. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  preview: boolean;
  onPreviewChange: (preview: boolean) => void;
  placeholder?: string | undefined;
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const editing = useMarkdownEditing(fieldRef, value, onChange);
  const rendered = preview ? renderMarkdown(value, { ticketHref }) : null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {title}
        </span>
        <MarkdownTabs id={id} title={title} preview={preview} onPreviewChange={onPreviewChange} />
      </div>
      <div
        role="tabpanel"
        id={`${id}-panel-write`}
        aria-labelledby={`${id}-tab-write`}
        hidden={preview}
      >
        <Textarea
          id={id}
          ref={fieldRef}
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={editing.onKeyDown}
          onPaste={editing.onPaste}
          placeholder={placeholder}
        />
      </div>
      <div
        role="tabpanel"
        id={`${id}-panel-preview`}
        aria-labelledby={`${id}-tab-preview`}
        hidden={!preview}
        className="prose-card min-h-24 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3"
      >
        {rendered ?? (
          <span className="text-xs text-[var(--muted-foreground)]">Nothing to preview yet</span>
        )}
      </div>
      <MarkdownHelp />
    </div>
  );
}
