import { Copy, ExternalLink, X } from "lucide-react";
import { useEffect, useRef, type ReactElement, type ReactNode } from "react";
import type { Card } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useTitleEdit } from "./useTitleEdit";

const ICON_BUTTON =
  "inline-flex items-center gap-1.5 rounded-md border border-transparent px-2 py-[5px] text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

const TITLE =
  "m-0 mt-2.5 max-w-[26ch] text-balance text-[26px] font-semibold leading-tight tracking-[-0.01em] text-[var(--foreground)]";

/**
 * The Ticket's head: the key with its copy button, the Phase, "Open as page" and Close when it is a
 * dialog, the title as the view's heading (a click edits it inline), the summary as the lead, and
 * the actions row. `titleWrap` lets the dialog name itself by the heading.
 */
export function TicketHead({
  card,
  phase,
  level,
  titleWrap = (heading) => heading,
  readOnly,
  onSaveTitle,
  onCopyKey,
  onOpenPage,
  onClose,
  page = false,
  actions,
}: {
  card: Card;
  phase: { number: number; name: string | null } | null;
  /** h1 on the Ticket's page, h2 inside the dialog. */
  level: 1 | 2;
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
  readOnly: boolean;
  onSaveTitle: (title: string) => void;
  onCopyKey: (key: string) => void;
  onOpenPage?: (() => void) | undefined;
  onClose?: (() => void) | undefined;
  page?: boolean | undefined;
  actions: ReactNode;
}) {
  const title = useTitleEdit({ title: card.title, onSave: onSaveTitle });
  const titleButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const Heading = level === 1 ? "h1" : "h2";

  // Leaving the field gives the focus back to the heading it replaced.
  useEffect(() => {
    if (wasEditing.current && !title.editing) titleButton.current?.focus();
    wasEditing.current = title.editing;
  }, [title.editing]);

  return (
    <div
      className={cn(
        "border-b border-[var(--border-soft)] bg-[var(--background)] px-4 sm:px-7",
        page ? "pt-6" : "pt-[18px]",
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5 text-[13px]">
        {card.ticket_key ? (
          <span className="inline-flex items-center gap-1.5 font-mono text-[12.5px] text-[var(--muted-foreground)]">
            {card.ticket_key}
            <button
              type="button"
              title="Copy key"
              aria-label={`Copy key ${card.ticket_key}`}
              onClick={() => onCopyKey(card.ticket_key ?? "")}
              className="inline-flex rounded p-0.5 text-[var(--foreground-faint)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
            >
              <Copy size={13} aria-hidden="true" />
            </button>
          </span>
        ) : null}
        {phase ? (
          <span className="text-[var(--muted-foreground)]">
            Phase {phase.number}
            {phase.name ? (
              <>
                {" · "}
                <b className="font-medium text-[var(--foreground)]">{phase.name}</b>
              </>
            ) : null}
          </span>
        ) : null}
        <span className="flex-1" />
        {onOpenPage ? (
          <button type="button" className={ICON_BUTTON} onClick={onOpenPage}>
            <ExternalLink size={15} aria-hidden="true" />
            <span>Open as page</span>
          </button>
        ) : null}
        {onClose ? (
          <button type="button" aria-label="Close dialog" className={ICON_BUTTON} onClick={onClose}>
            <X size={15} aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {title.editing ? (
        <input
          aria-label="Title"
          autoFocus
          data-keeps-escape=""
          value={title.draft}
          maxLength={200}
          onChange={(event) => title.change(event.target.value)}
          onKeyDown={title.onKeyDown}
          onBlur={(event) => title.save(event.currentTarget.value)}
          className={cn(
            TITLE,
            "w-full max-w-none rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 outline-none focus-visible:border-[var(--ring)]",
          )}
        />
      ) : (
        titleWrap(
          <Heading className={TITLE}>
            {readOnly ? (
              card.title
            ) : (
              <button
                ref={titleButton}
                type="button"
                title="Click to edit the title"
                onClick={title.start}
                className="cursor-text rounded-md text-left hover:bg-[var(--surface-raised)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
              >
                {card.title}
              </button>
            )}
          </Heading>,
        )
      )}
      {card.summary ? (
        <p className="m-0 mt-2 max-w-[62ch] text-[15.5px] leading-normal text-[var(--muted-foreground)]">
          {card.summary}
        </p>
      ) : null}
      {actions}
    </div>
  );
}
