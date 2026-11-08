import { ChevronLeft, ExternalLink, X } from "lucide-react";
import type { ReactElement, ReactNode } from "react";
import type { Discussion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { askedLine } from "./discussionRules";

const ICON_BUTTON =
  "inline-flex items-center gap-1.5 rounded-md border border-transparent px-2 py-[5px] text-[13px] text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]";

const TITLE =
  "m-0 mt-2.5 max-w-[40ch] text-balance text-[24px] font-semibold leading-tight tracking-[-0.01em] text-[var(--foreground)]";

/**
 * The discussion's head, the Ticket head's shape: Back to the Ticket, the Ticket's key and
 * "Discussion", Open as page and Close where the host offers them; the question as the view's
 * heading, the line "Asked by … · n agents · round r of max", then the sign and the actions.
 */
export function DiscussionHead({
  discussion,
  level,
  titleWrap = (heading) => heading,
  page,
  onBack,
  onOpenPage,
  onClose,
  children,
}: {
  discussion: Discussion;
  /** h1 on the page, h2 inside the dialog and on the Discussions page. */
  level: 1 | 2;
  titleWrap?: ((heading: ReactElement) => ReactElement) | undefined;
  page: boolean;
  onBack?: (() => void) | undefined;
  onOpenPage?: (() => void) | undefined;
  onClose?: (() => void) | undefined;
  /** The sign and the actions row. */
  children: ReactNode;
}) {
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <div
      className={cn(
        "border-b border-[var(--border-soft)] bg-[var(--background)] px-4 sm:px-7",
        page ? "pt-6" : "pt-[18px]",
      )}
    >
      <div className="flex flex-wrap items-center gap-2.5 text-[13px]">
        {onBack ? (
          <button type="button" className={cn(ICON_BUTTON, "-ml-2")} onClick={onBack}>
            <ChevronLeft size={15} aria-hidden="true" />
            <span>Back to the Ticket</span>
          </button>
        ) : null}
        {discussion.ticket_key ? (
          <span className="font-mono text-[12.5px] text-[var(--muted-foreground)]">
            {discussion.ticket_key}
          </span>
        ) : null}
        <span className="text-[var(--muted-foreground)]">
          {discussion.ticket_key ? "· " : null}
          <b className="font-medium text-[var(--foreground)]">Discussion</b>
        </span>
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
      {titleWrap(<Heading className={TITLE}>{discussion.goal}</Heading>)}
      <p className="m-0 mt-2 text-[13.5px] text-[var(--muted-foreground)]">
        {askedLine(discussion)}
      </p>
      {children}
    </div>
  );
}
