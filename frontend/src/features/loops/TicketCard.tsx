import type { DraggableSyntheticListeners } from "@dnd-kit/core";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, Check, Flag, GripVertical } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Chip, StateChip } from "@/components/ui/chip";
import type { Card } from "@/lib/types";
import { cn, isOverdue } from "@/lib/utils";
import type { DragData } from "./dragData";

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

/** What the card says the Ticket is about: the face's summary, else the stored one. */
function cardSummary(card: Pick<Card, "face" | "summary">): string {
  return (card.face?.summary ?? "").trim() || card.summary.trim();
}

/** Why a held Ticket is held, for a pointer: what blocks it, else the reason of its wait. */
function heldReason(card: Card): string | undefined {
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
 * row with the key, the state only when it needs attention (Needs input, Blocked), the priority and
 * due date when set, "done" once completed, "Needs a person" for a person's task, and the owner.
 * The title is the button that opens the Ticket (Enter or a click); it covers the whole card, so a
 * pointer drags the card from anywhere on it. The grip beside the title ("Move <title>") is the
 * keyboard's drag handle: Space or Enter picks the card up, the arrow keys move it.
 */
export function TicketCard({
  card,
  onOpen,
  overlay = false,
}: {
  card: Card;
  onOpen?: (card: Card) => void;
  overlay?: boolean;
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

  const summary = cardSummary(card);
  const held = card.state === "needs_input" || card.state === "blocked" ? card.state : null;
  const done = card.completed_at !== null;
  // A manual Ticket with a key was added while the Loop's plan executes: outside the plan.
  const unplanned = card.kind === "manual" && card.ticket_key !== null;
  const priority = card.priority === "none" ? null : card.priority;

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
          // Above the title's full-card click area, so the grip takes its own pointer and keys.
          <div className="relative z-10 -mr-1 flex shrink-0 items-center">
            <button
              type="button"
              ref={setActivatorNodeRef}
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
          <span className="font-mono text-[11px] text-[var(--foreground-faint)]">
            {card.ticket_key}
          </span>
        ) : null}
        {held && !done ? <StateChip state={held} compact title={heldReason(card)} /> : null}
        {card.human_action_required && !done ? (
          <Chip className="px-1.5 py-px text-xs">Needs a person</Chip>
        ) : null}
        {unplanned ? (
          <span title="Added outside the plan; it never blocks the plan or the Loop's completion">
            Unplanned
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
          <span
            className={cn(
              "inline-flex items-center gap-1 tabular-nums",
              isOverdue(card.due_at, card.completed_at) && "text-[var(--destructive)]",
            )}
          >
            <CalendarClock size={12} aria-hidden="true" />
            {new Date(card.due_at).toLocaleDateString()}
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
