import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarClock, CheckSquare, MessageSquare } from "lucide-react";
import { LabelChip } from "@/components/ui/badge";
import { cn, isOverdue } from "@/lib/utils";
import type { Card } from "@/lib/types";

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
    data: { type: "card", cardId: card.id, listId: card.list_id },
    disabled: overlay,
  });
  const style = overlay
    ? undefined
    : {
        transform: CSS.Transform.toString(sortable.transform),
        transition: sortable.transition,
      };

  const overdue = isOverdue(card.due_at, card.completed_at);

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
