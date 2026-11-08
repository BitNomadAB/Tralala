import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, Check, Flag } from "lucide-react";
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
 * A Ticket on the Kanban, the first line of its face: the title, the plain summary, and a bottom
 * row with the key, the state only when it needs attention (Needs input, Blocked), the priority and
 * due date when set, "done" once completed, "Needs a person" for a person's task, and the owner.
 * The title is the button that opens the Ticket and the drag handle; it covers the whole card.
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
  const sortable = useSortable({
    id: card.id,
    data: { type: "card", cardId: card.id, listId: card.list_id } satisfies DragData,
    disabled: overlay,
  });
  const style = overlay
    ? undefined
    : { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition };

  const summary = cardSummary(card);
  const held = card.state === "needs_input" || card.state === "blocked" ? card.state : null;
  const done = card.completed_at !== null;
  // A manual Ticket with a key was added while the Loop's plan executes: outside the plan.
  const unplanned = card.kind === "manual" && card.ticket_key !== null;
  const priority = card.priority === "none" ? null : card.priority;

  return (
    <li
      ref={overlay ? undefined : sortable.setNodeRef}
      style={style}
      className={cn(
        "relative grid gap-1 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-raised)] px-2.5 py-2 transition-colors hover:border-[var(--border)]",
        !overlay && sortable.isDragging && "opacity-40",
        overlay && "rotate-2 shadow-xl",
      )}
    >
      <button
        type="button"
        className="line-clamp-2 text-left text-base font-semibold leading-snug text-[var(--foreground)] after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-[var(--ring)]"
        onClick={() => onOpen?.(card)}
        {...(overlay ? {} : sortable.attributes)}
        {...(overlay ? {} : sortable.listeners)}
      >
        {card.title}
      </button>
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
