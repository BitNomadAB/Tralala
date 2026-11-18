import { CheckSquare } from "lucide-react";
import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Checklist, ChecklistItem } from "@/lib/types";

/**
 * The Ticket's checklists in the rail's More: each with its count, its items as checkboxes named by
 * their text (the whole row, at least 24 px high, is the target), and a form to add an item; a form
 * to add a checklist above them. The heading sits one level under the Ticket's title (`level`).
 */
export function CardChecklists({
  level,
  checklists,
  checklistTitle,
  onChecklistTitleChange,
  onAddChecklist,
  itemText,
  onItemTextChange,
  onAddItem,
  onToggleItem,
}: {
  level: 2 | 3;
  checklists: Checklist[];
  checklistTitle: string;
  onChecklistTitleChange: (title: string) => void;
  onAddChecklist: (title: string) => void;
  itemText: Record<string, string>;
  onItemTextChange: (checklistId: string, text: string) => void;
  onAddItem: (checklistId: string, text: string) => void;
  onToggleItem: (item: ChecklistItem) => void;
}) {
  const headingId = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={headingId}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <Heading id={headingId} className="m-0 text-sm font-semibold">
          Checklists
        </Heading>
        <form
          className="flex gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            if (checklistTitle.trim()) onAddChecklist(checklistTitle.trim());
          }}
        >
          <Input
            className="h-8 w-40"
            placeholder="New checklist"
            aria-label="New checklist title"
            value={checklistTitle}
            onChange={(event) => onChecklistTitleChange(event.target.value)}
          />
          <Button
            size="sm"
            type="submit"
            aria-label="Add checklist"
            disabled={!checklistTitle.trim()}
          >
            Add
          </Button>
        </form>
      </div>
      {checklists.length === 0 ? (
        <p className="text-xs text-[var(--muted-foreground)]">No checklists yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {checklists.map((checklist) => (
            <ChecklistBlock
              key={checklist.id}
              checklist={checklist}
              text={itemText[checklist.id] ?? ""}
              onTextChange={(text) => onItemTextChange(checklist.id, text)}
              onAddItem={(text) => onAddItem(checklist.id, text)}
              onToggleItem={onToggleItem}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** One checklist: its title and count, its items, and the form that adds one. */
function ChecklistBlock({
  checklist,
  text,
  onTextChange,
  onAddItem,
  onToggleItem,
}: {
  checklist: Checklist;
  text: string;
  onTextChange: (text: string) => void;
  onAddItem: (text: string) => void;
  onToggleItem: (item: ChecklistItem) => void;
}) {
  const done = checklist.items.filter((item) => item.completed).length;
  return (
    <div className="rounded-lg border border-[var(--border)] p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <CheckSquare size={14} aria-hidden="true" className="text-[var(--muted-foreground)]" />
        <span className="text-xs font-semibold">{checklist.title}</span>
        <span className="text-xs text-[var(--muted-foreground)]">
          {done}/{checklist.items.length}
        </span>
      </div>
      <ul aria-label={checklist.title} className="m-0 flex list-none flex-col p-0">
        {checklist.items.map((item) => (
          <li key={item.id}>
            <label className="flex min-h-6 cursor-pointer items-center gap-2 rounded px-0.5 text-xs hover:bg-[var(--surface-raised)]">
              <input
                type="checkbox"
                checked={item.completed}
                onChange={() => onToggleItem(item)}
                className="size-4 shrink-0 accent-[var(--primary)]"
              />
              <span className={item.completed ? "text-[var(--muted-foreground)] line-through" : ""}>
                {item.text}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <form
        className="mt-1.5 flex gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) onAddItem(text.trim());
        }}
      >
        <Input
          className="h-7 text-xs"
          placeholder="Add item"
          aria-label={`Add item to ${checklist.title}`}
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
        />
        <Button
          size="sm"
          variant="ghost"
          type="submit"
          aria-label={`Add item to ${checklist.title}`}
        >
          Add
        </Button>
      </form>
    </div>
  );
}
