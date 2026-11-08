import { CircleCheck, Clock, Ellipsis, MessageSquare, Paperclip, Play } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";

export type PrimaryAction =
  | { kind: "start"; onStart: () => void }
  | { kind: "complete"; onComplete: () => void; blocked: string | null }
  | null;

/**
 * The actions row under the title: one primary decision (Start work, or Mark complete), then Mark
 * as waiting, Comment, Add file, and a quiet "more" with Copy link, Ask the agents, Mark
 * incomplete for a completed Ticket, and Archive. A read-only Ticket keeps Comment and Copy link.
 */
export function TicketActions({
  primary,
  pending,
  readOnly,
  completed,
  waiting,
  onWait,
  onComment,
  onAddFile,
  onCopyLink,
  onAsk,
  onReopen,
  onArchive,
}: {
  primary: PrimaryAction;
  pending: boolean;
  readOnly: boolean;
  completed: boolean;
  waiting: boolean;
  onWait: () => void;
  onComment: () => void;
  onAddFile: () => void;
  onCopyLink: () => void;
  onAsk: () => void;
  onReopen: () => void;
  onArchive: () => void;
}) {
  return (
    <div className="mb-4 mt-[18px] flex flex-wrap gap-2">
      {primary?.kind === "start" && !readOnly ? (
        <Button size="sm" disabled={pending} onClick={primary.onStart}>
          <Play size={15} aria-hidden="true" /> Start work
        </Button>
      ) : null}
      {primary?.kind === "complete" && !readOnly ? (
        <Button
          size="sm"
          disabled={pending || primary.blocked !== null}
          title={primary.blocked ?? undefined}
          onClick={primary.onComplete}
        >
          <CircleCheck size={15} aria-hidden="true" /> Mark complete
        </Button>
      ) : null}
      {completed || readOnly ? null : (
        <Button
          variant="secondary"
          size="sm"
          disabled={waiting}
          title={waiting ? "It already waits; clear the wait in the rail" : undefined}
          onClick={onWait}
        >
          <Clock size={15} aria-hidden="true" /> Mark as waiting
        </Button>
      )}
      <Button variant="secondary" size="sm" onClick={onComment}>
        <MessageSquare size={15} aria-hidden="true" /> Comment
      </Button>
      {readOnly ? null : (
        <Button variant="secondary" size="sm" onClick={onAddFile}>
          <Paperclip size={15} aria-hidden="true" /> Add file
        </Button>
      )}
      <MoreMenu
        items={[
          { label: "Copy link", onSelect: onCopyLink },
          ...(readOnly ? [] : [{ label: "Ask the agents", onSelect: onAsk }]),
          ...(completed && !readOnly ? [{ label: "Mark incomplete", onSelect: onReopen }] : []),
          ...(readOnly ? [] : [{ label: "Archive", onSelect: onArchive }]),
        ]}
      />
    </div>
  );
}

/**
 * The quiet "more" button and the few actions it shows. Escape or a press outside closes it, and
 * Escape inside it never reaches the dialog around it.
 */
function MoreMenu({ items }: { items: { label: string; onSelect: () => void }[] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);

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

  /** Escape closes the menu and gives the focus back to its button. */
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
    root.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }

  return (
    <div ref={root} className="relative" data-keeps-escape={open ? "" : undefined}>
      <Button
        variant="quiet"
        size="icon"
        aria-label="More actions"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen(!open)}
        onKeyDown={onKeyDown}
      >
        <Ellipsis size={15} aria-hidden="true" />
      </Button>
      {open ? (
        <ul
          id={panelId}
          aria-label="More actions"
          className="absolute left-0 z-20 m-0 mt-1.5 grid min-w-44 list-none gap-px rounded-lg border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-xl"
        >
          {items.map((item) => (
            <li key={item.label}>
              <button
                type="button"
                autoFocus={item === items[0]}
                onKeyDown={onKeyDown}
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
                className="w-full rounded-md px-2.5 py-2 text-left text-sm text-[var(--foreground)] hover:bg-[var(--surface-raised)] focus-visible:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
