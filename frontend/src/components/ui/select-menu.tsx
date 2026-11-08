import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { rovingIndex } from "./roving";

/** The options of an open listbox, in order. */
function optionElements(list: HTMLElement | null): HTMLElement[] {
  return Array.from(list?.querySelectorAll<HTMLElement>('[role="option"]') ?? []);
}

export interface SelectMenuOption<T extends string> {
  value: T;
  label: string;
  /** A number shown muted on the right ("13" Tickets in the column). */
  count?: number | undefined;
}

/**
 * A choice among a few values, the way the rail shows a Ticket's column: a button with the current
 * label opens a `listbox` of `option`s. Up/Down, Home and End move between the options, Enter or
 * Space chooses one, Escape closes and gives the focus back to the button, and so does a click
 * outside. `onChange` is called once per choice, and not for the value that is already chosen.
 */
export function SelectMenu<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
  defaultOpen = false,
  onClose,
  className,
}: {
  /** What is chosen ("Column"); the button reads "Column: Backlog". */
  label: string;
  value: T;
  options: readonly SelectMenuOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean | undefined;
  /** Opens at once, for a value that turns into this menu when it is clicked (a fact in a rail). */
  defaultOpen?: boolean | undefined;
  /** Called each time the menu closes, after `onChange` when a value was chosen. */
  onClose?: (() => void) | undefined;
  className?: string | undefined;
}) {
  const listId = useId();
  const [open, setOpen] = useState(defaultOpen);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const current = options.find((option) => option.value === value);

  // Opening puts the focus on the chosen option (or the first), as a native select does.
  useEffect(() => {
    if (!open) return;
    const items = optionElements(list.current);
    const chosen = items.find((item) => item.getAttribute("aria-selected") === "true");
    (chosen ?? items[0])?.focus();
  }, [open]);

  // A press anywhere outside closes the menu without choosing.
  useEffect(() => {
    if (!open) return;
    function outside(event: MouseEvent) {
      if (event.target instanceof Node && root.current?.contains(event.target)) return;
      setOpen(false);
      onClose?.();
    }
    document.addEventListener("mousedown", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
    };
  }, [open, onClose]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  function choose(next: T) {
    setOpen(false);
    button.current?.focus();
    if (next !== value) onChange(next);
    onClose?.();
  }

  function onOptionKeyDown(event: KeyboardEvent<HTMLElement>, option: T) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(option);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      onClose?.();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      onClose?.();
      return;
    }
    const items = optionElements(list.current);
    const next = rovingIndex(
      event.key,
      items.indexOf(event.currentTarget),
      items.length,
      "vertical",
    );
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus();
  }

  return (
    <div ref={root} className={cn("relative", className)}>
      <button
        ref={button}
        type="button"
        aria-label={`${label}: ${current?.label ?? "none"}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={disabled}
        onClick={() => {
          setOpen(!open);
          if (open) onClose?.();
        }}
        onKeyDown={(event) => {
          if (open || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
          event.preventDefault();
          setOpen(true);
        }}
        className="inline-flex w-full cursor-pointer items-center justify-between gap-2.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-[9px] text-sm font-semibold text-[var(--foreground)] transition-colors hover:border-[var(--foreground-faint)] disabled:cursor-default disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
      >
        <span className="truncate">{current?.label ?? ""}</span>
        <ChevronDown
          size={14}
          aria-hidden="true"
          className="shrink-0 text-[var(--muted-foreground)]"
        />
      </button>
      {open ? (
        <div
          ref={list}
          id={listId}
          role="listbox"
          aria-label={label}
          className="absolute z-20 mt-1.5 grid w-full gap-px rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-xl"
        >
          {options.map((option) => (
            <div
              key={option.value}
              role="option"
              aria-selected={option.value === value}
              // The count is part of the name ("Backlog, 13"), read as one phrase.
              aria-label={
                option.count === undefined ? undefined : `${option.label}, ${String(option.count)}`
              }
              tabIndex={-1}
              onClick={() => choose(option.value)}
              onKeyDown={(event) => onOptionKeyDown(event, option.value)}
              className="flex cursor-pointer items-center justify-between gap-3 rounded-md px-2.5 py-2 text-sm text-[var(--foreground)] outline-none hover:bg-[var(--surface-raised)] focus-visible:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-[var(--ring)] aria-selected:font-semibold"
            >
              <span className="truncate">{option.label}</span>
              {option.count === undefined ? null : (
                <small className="text-xs font-normal tabular-nums text-[var(--foreground-faint)]">
                  {option.count}
                </small>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
