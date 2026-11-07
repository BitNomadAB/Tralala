import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, CheckSquare, CircleHelp, Lock, MessageSquare, User } from "lucide-react";
import { LabelChip } from "@/components/ui/badge";
import type { Card } from "@/lib/types";
import { cn, isOverdue } from "@/lib/utils";
import type { DragData } from "./dragData";

const priorityTone: Record<Card["priority"], string> = {
  none: "border-[var(--border)] text-[var(--muted-foreground)]",
  low: "border-[var(--border)] text-[var(--muted-foreground)]",
  medium: "border-[var(--warning)] text-[var(--warning)]",
  high: "border-[var(--destructive)] text-[var(--destructive)]",
  urgent: "border-[var(--destructive)] text-[var(--destructive)]",
};

export function CardTile({
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
    : {
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      };

  const overdue = isOverdue(card.due_at, card.completed_at);
  // A manual Ticket with a key was added while the Loop's plan executes: outside the plan.
  const unplanned = card.kind === "manual" && card.ticket_key !== null;
  // The server's state: a marker for what holds the Ticket up, none when it is ready or done.
  const held = card.state === "needs_input" || card.state === "blocked";

  return (
    <li
      ref={overlay ? undefined : sortable.setNodeRef}
      style={style}
      className={cn(
        "group rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2.5 shadow-sm",
        !overlay && sortable.isDragging && "opacity-40",
        overlay && "rotate-2 shadow-xl",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          className="flex-1 text-left"
          onClick={() => onOpen?.(card)}
          {...(overlay ? {} : sortable.attributes)}
          {...(overlay ? {} : sortable.listeners)}
        >
          {card.ticket_key ? (
            <span className="mb-0.5 block font-mono text-[10px] text-[var(--muted-foreground)]">
              {card.ticket_key}
            </span>
          ) : null}
          <span className="text-sm font-medium leading-snug text-[var(--foreground)]">
            {card.title}
          </span>
        </button>
        {card.priority !== "none" ? (
          <span
            className={cn(
              "mt-0.5 shrink-0 rounded border px-1 py-0.5 text-[10px] uppercase tracking-wide",
              priorityTone[card.priority],
            )}
            title={`Priority: ${card.priority}`}
          >
            {card.priority}
          </span>
        ) : null}
      </div>

      {card.human_action_required || held || card.kind === "qa" || unplanned ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {card.human_action_required ? (
            <span className="inline-flex items-center gap-1 rounded border border-[var(--warning)] px-1.5 py-0.5 text-[10px] text-[var(--warning)]">
              <User size={10} /> Human action required
            </span>
          ) : null}
          {card.state === "needs_input" ? (
            <span
              className="inline-flex items-center gap-1 rounded border border-[var(--warning)] px-1.5 py-0.5 text-[10px] text-[var(--warning)]"
              title={card.waiting_reason || undefined}
            >
              <CircleHelp size={10} /> Needs input
            </span>
          ) : null}
          {card.state === "blocked" ? (
            <span
              className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
              title={
                card.blockers.map((blocker) => blocker.key ?? blocker.reason).join(", ") ||
                card.waiting_reason ||
                undefined
              }
            >
              <Lock size={10} /> Blocked
            </span>
          ) : null}
          {unplanned ? (
            <span
              className="inline-flex items-center rounded border border-dashed border-[var(--border)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
              title="Added outside the plan; it never blocks the plan or the Loop's completion"
            >
              Unplanned
            </span>
          ) : null}
          {card.kind === "qa" ? (
            <span className="inline-flex items-center rounded border border-[var(--primary)] px-1.5 py-0.5 text-[10px] text-[var(--primary)]">
              QA
            </span>
          ) : null}
        </div>
      ) : null}

      {card.labels.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {card.labels.map((label) => (
            <LabelChip key={label.id} name={label.name} color={label.color} />
          ))}
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
        {card.due_at ? (
          <span
            className={cn("inline-flex items-center gap-1", overdue && "text-[var(--destructive)]")}
          >
            <CalendarClock size={12} />
            {new Date(card.due_at).toLocaleDateString()}
          </span>
        ) : null}
        {card.checklist_total > 0 ? (
          <span className="inline-flex items-center gap-1">
            <CheckSquare size={12} />
            {card.checklist_completed}/{card.checklist_total}
          </span>
        ) : null}
        {card.comment_count > 0 ? (
          <span className="inline-flex items-center gap-1">
            <MessageSquare size={12} />
            {card.comment_count}
          </span>
        ) : null}
        {card.completed_at ? (
          <span className="ml-auto rounded bg-[var(--surface-raised)] px-1.5 py-0.5 text-[10px] uppercase text-[var(--success)]">
            done
          </span>
        ) : null}
      </div>
    </li>
  );
}
