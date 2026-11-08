import { MoreHorizontal } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { rovingIndex } from "./roving";

/** The enabled items of an open menu, in order. */
function itemElements(menu: HTMLElement | null): HTMLElement[] {
  return Array.from(
    menu?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [],
  );
}

export interface MenuItem {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  /** Shown but not chosen; `hint` says why ("Archive the board first"). */
  disabled?: boolean | undefined;
  hint?: string | undefined;
  /** An action that removes something, in the danger colour. */
  danger?: boolean | undefined;
}

/**
 * The quiet "more" control: a button (an ellipsis, named by `label`) opens a `menu` of actions.
 * Opening focuses the first item; Up/Down, Home and End move between them, Enter or Space runs one,
 * Escape closes and gives the focus back to the button, and so does a click outside. A disabled
 * item stays in the list, so a person sees the action and why it is not available.
 */
export function Menu({
  label,
  items,
  className,
}: {
  label: string;
  items: readonly MenuItem[];
  className?: string | undefined;
}) {
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) itemElements(menu.current)[0]?.focus();
  }, [open]);

  // A press anywhere outside closes the menu without running anything.
  useEffect(() => {
    if (!open) return;
    function outside(event: MouseEvent) {
      if (event.target instanceof Node && root.current?.contains(event.target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
    };
  }, [open]);

  function close() {
    setOpen(false);
    button.current?.focus();
  }

  function run(item: MenuItem) {
    if (item.disabled) return;
    close();
    item.onSelect();
  }

  function onItemKeyDown(event: KeyboardEvent<HTMLElement>, item: MenuItem) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      run(item);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    const enabled = itemElements(menu.current);
    const next = rovingIndex(
      event.key,
      enabled.indexOf(event.currentTarget),
      enabled.length,
      "vertical",
    );
    if (next === null) return;
    event.preventDefault();
    enabled[next]?.focus();
  }

  return (
    // While open, Escape belongs to the menu: a dialog around it (`DialogFrame`) stays open.
    <div ref={root} className={cn("relative", className)} data-keeps-escape={open ? "" : undefined}>
      <button
        ref={button}
        type="button"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((was) => !was)}
        onKeyDown={(event) => {
          if (open || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
          event.preventDefault();
          setOpen(true);
        }}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={label}
          className="absolute right-0 z-20 mt-1.5 grid min-w-52 gap-px rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-xl"
        >
          {items.map((item) => (
            <div
              key={item.label}
              role="menuitem"
              tabIndex={-1}
              aria-disabled={item.disabled ? true : undefined}
              // A disabled item says why in its name ("Delete board: Archive the board first").
              aria-label={item.disabled && item.hint ? `${item.label}: ${item.hint}` : undefined}
              title={item.hint}
              onClick={() => run(item)}
              onKeyDown={(event) => onItemKeyDown(event, item)}
              className={cn(
                "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none hover:bg-[var(--surface-raised)] focus-visible:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]",
                item.danger ? "text-[var(--destructive)]" : "text-[var(--foreground)]",
                item.disabled && "cursor-default opacity-50 hover:bg-transparent",
              )}
            >
              {item.icon === undefined ? null : (
                <span aria-hidden="true" className="text-[var(--muted-foreground)]">
                  {item.icon}
                </span>
              )}
              <span>{item.label}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
