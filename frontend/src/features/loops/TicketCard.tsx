import type { DraggableSyntheticListeners } from "@dnd-kit/core";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, Check, Flag, GripVertical } from "lucide-react";
import { useEffect, useRef } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Chip, StateChip } from "@/components/ui/chip";
import { Menu, type MenuItem } from "@/components/ui/menu";
import { NoReportChip } from "@/features/cards/NoReport";
import { NOT_DONE_REASON } from "@/features/cards/ticketWork";
import type { Card } from "@/lib/types";
import { cn, isOverdue } from "@/lib/utils";
import type { DragData } from "./dragData";
import type { CardControl } from "./useKanbanMoves";

const PRIORITY_WORDS: Record<Exclude<Card["priority"], "none">, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

const PRIORITY_TONES: Record<Exclude<Card["priority"], "none">, string> = {
  low: "text-[var(--muted-foreground)]",
  medium: "text-[var(--warning)]",
  high: "text-[var(--destructive)]",
  urgent: "text-[var(--destructive)]",
};

/** What "Unplanned" on a card means. */
const UNPLANNED = "Added outside the plan; it never blocks the plan or the Loop's completion";

/** What the card says the Ticket is about: the face's summary, else the stored one. */
function cardSummary(card: Pick<Card, "face" | "summary">): string {
  return (card.face?.summary ?? "").trim() || card.summary.trim();
}

/**
 * Why a held Ticket is held, on hover and for a screen reader: what blocks it, else its wait; for
 * one left undone, that its Loop was closed.
 */
function heldReason(card: Card): string | undefined {
  if (card.state === "not_done") return NOT_DONE_REASON;
  const blockers = card.blockers.map((blocker) => blocker.key ?? blocker.reason).join(", ");
  return (card.state === "blocked" && blockers) || card.waiting_reason || undefined;
}

/**
 * The pointer half of dnd-kit's listeners. A pointer may drag the card by any part of it, since
 * the board's pointer sensor waits for 4 px of movement and a click still opens the Ticket; the
 * keyboard half stays on the grip, because dnd-kit's keyboard sensor takes Enter and Space.
 */
function pointerListeners(listeners: DraggableSyntheticListeners): DraggableSyntheticListeners {
  if (!listeners) return undefined;
  return Object.fromEntries(
    Object.entries(listeners).filter(([event]) => event.startsWith("onPointer")),
  );
}

const GRIP =
  "inline-flex size-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]";

/**
 * A Ticket on the Kanban, the first line of its face: the title, the plain summary, and a bottom
 * row with the key, the state unless it is Ready (Needs input, Blocked, or Not done once its Loop
 * was closed without it), "No report" while a key that took it has not reported on it, the
 * priority and due date when set, "done" once completed, "Needs a person" for a person's task that
 * can still be done, and the owner.
 * The title is the button that opens the Ticket (Enter or a click); it covers the whole card, so a
 * pointer drags the card from anywhere on it. The grip beside the title ("Move <title>") is the
 * keyboard's drag handle: Space or Enter picks the card up, the arrow keys move it. `actions`, the
 * menu after the grip ("Actions for <title>"), moves it without dragging. `focus` names the control
 * that takes the focus once the card shows where it moved to; `onFocused` says it did.
 */
export function TicketCard({
  card,
  onOpen,
  overlay = false,
  actions,
  focus = null,
  onFocused,
}: {
  card: Card;
  onOpen?: (card: Card) => void;
  overlay?: boolean;
  actions?: readonly MenuItem[] | undefined;
  focus?: CardControl | null | undefined;
  onFocused?: (() => void) | undefined;
}) {
  // Destructured, so the ref callbacks stay separate from the values read while rendering.
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: card.id,
    data: { type: "card", cardId: card.id, listId: card.list_id } satisfies DragData,
    disabled: overlay,
  });
  const style = overlay ? undefined : { transform: CSS.Transform.toString(transform), transition };
  const controls = useRef<HTMLDivElement>(null);

  // A moved card is rendered anew in its column, so the focus is given back to it here.
  useEffect(() => {
    if (focus === null) return;
    const selector = focus === "grip" ? "[data-card-grip]" : '[aria-haspopup="menu"]';
    controls.current?.querySelector<HTMLElement>(selector)?.focus();
    onFocused?.();
  }, [focus, onFocused]);

  const summary = cardSummary(card);
  // Ready is the quiet case; every other state is shown.
  const held = card.state === "ready" ? null : card.state;
  const done = card.completed_at !== null;
  const notDone = card.state === "not_done";
  // A manual Ticket with a key was added while the Loop's plan executes: outside the plan.
  const unplanned = card.kind === "manual" && card.ticket_key !== null;
  const priority = card.priority === "none" ? null : card.priority;
  const overdue = card.due_at !== null && isOverdue(card.due_at, card.completed_at);

  return (
    <li
      ref={overlay ? undefined : setNodeRef}
      style={style}
      className={cn(
        "relative grid gap-1 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-raised)] px-2.5 py-2 transition-colors hover:border-[var(--border)]",
        !overlay && isDragging && "opacity-40",
        overlay && "rotate-2 shadow-xl",
      )}
    >
      <div className="flex items-start gap-1">
        <button
          type="button"
          // The Ticket dialog gives the focus back to this button when it closes.
          data-ticket-open={card.id}
          className="line-clamp-2 min-w-0 flex-1 text-left text-base font-semibold leading-snug text-[var(--foreground)] after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-[var(--ring)]"
          onClick={() => onOpen?.(card)}
          {...(overlay ? {} : pointerListeners(listeners))}
        >
          {card.title}
        </button>
        {overlay ? (
          <span aria-hidden="true" className={cn(GRIP, "-mr-1")}>
            <GripVertical size={14} />
          </span>
        ) : (
          // Positioned after the title, so it is drawn over the title's full-card click area and
          // takes its own pointer; no z-index, so an open menu still covers the cards below.
          // The negative margins keep the card as low as a line of its title.
          <div ref={controls} className="relative -my-1 -mr-1 flex shrink-0 items-center">
            <button
              type="button"
              ref={setActivatorNodeRef}
              data-card-grip=""
              aria-label={`Move ${card.title}`}
              className={cn(
                GRIP,
                "cursor-grab hover:bg-[var(--surface)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]",
              )}
              {...attributes}
              {...listeners}
            >
              <GripVertical size={14} aria-hidden="true" />
            </button>
            {actions ? <Menu label={`Actions for ${card.title}`} items={actions} /> : null}
          </div>
        )}
      </div>
      {summary ? (
        <p className="line-clamp-2 text-sm leading-snug text-[var(--muted-foreground)]">
          {summary}
        </p>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {card.ticket_key ? (
          // The key is what people say and search for, so it reads as strongly as the title.
          <span className="font-mono text-xs font-semibold text-[var(--foreground)]">
            {card.ticket_key}
          </span>
        ) : null}
        {held && !done ? <StateChip state={held} compact title={heldReason(card)} /> : null}
        <NoReportChip card={card} />
        {card.human_action_required && !done && !notDone ? (
          <Chip className="px-1.5 py-px text-xs">Needs a person</Chip>
        ) : null}
        {unplanned ? (
          <span title={UNPLANNED}>
            <span>Unplanned</span>
            {/* What the hover says, for a screen reader too. */}
            <span className="sr-only">: {UNPLANNED}</span>
          </span>
        ) : null}
        {card.kind === "qa" ? <span>QA</span> : null}
        {priority ? (
          <span className={cn("inline-flex items-center gap-1", PRIORITY_TONES[priority])}>
            <Flag size={12} aria-hidden="true" />
            {PRIORITY_WORDS[priority]}
          </span>
        ) : null}
        {card.due_at ? (
          // Overdue is said in a word, not by the colour alone (WCAG 1.4.1).
          <span
            className={cn(
              "inline-flex items-center gap-1 tabular-nums",
              overdue && "text-[var(--destructive)]",
            )}
          >
            <CalendarClock size={12} aria-hidden="true" />
            {/* The spaces keep the words apart for a screen reader; the flex row drops them. */}
            <span className="sr-only">Due</span>{" "}
            <time dateTime={card.due_at}>{new Date(card.due_at).toLocaleDateString()}</time>{" "}
            {overdue ? <span className="font-semibold">Overdue</span> : null}
          </span>
        ) : null}
        {done ? (
          <span className="inline-flex items-center gap-1 text-[var(--success)]">
            <Check size={12} aria-hidden="true" />
            done
          </span>
        ) : null}
        {card.assignee_name ? (
          <Avatar
            name={card.assignee_name}
            size="sm"
            label={`Owner: ${card.assignee_name}`}
            className="ml-auto"
          />
        ) : null}
      </div>
    </li>
  );
}
