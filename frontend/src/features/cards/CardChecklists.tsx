import { CheckSquare, Circle, CircleCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Checklist, ChecklistItem } from "@/lib/types";

export function CardChecklists({
  checklists,
  checklistTitle,
  onChecklistTitleChange,
  onAddChecklist,
  itemText,
  onItemTextChange,
  onAddItem,
  onToggleItem,
}: {
  checklists: Checklist[];
  checklistTitle: string;
  onChecklistTitleChange: (title: string) => void;
  onAddChecklist: (title: string) => void;
  itemText: Record<string, string>;
  onItemTextChange: (checklistId: string, text: string) => void;
  onAddItem: (checklistId: string, text: string) => void;
  onToggleItem: (item: ChecklistItem) => void;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Checklists</h3>
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
          <Button size="sm" type="submit" disabled={!checklistTitle.trim()}>
            Add
          </Button>
        </form>
      </div>
      {checklists.length === 0 ? (
        <p className="text-xs text-[var(--muted-foreground)]">No checklists yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {checklists.map((checklist) => (
            <div key={checklist.id} className="rounded-lg border border-[var(--border)] p-2.5">
              <div className="mb-1.5 flex items-center gap-2">
                <CheckSquare size={14} className="text-[var(--muted-foreground)]" />
                <span className="text-xs font-semibold">{checklist.title}</span>
                <span className="text-[11px] text-[var(--muted-foreground)]">
                  {checklist.items.filter((item) => item.completed).length}/{checklist.items.length}
                </span>
              </div>
              <ul className="flex flex-col gap-1">
                {checklist.items.map((item) => (
                  <li key={item.id} className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-pressed={item.completed}
                      aria-label={`${item.completed ? "Uncheck" : "Check"} ${item.text}`}
                      onClick={() => onToggleItem(item)}
                      className="text-[var(--muted-foreground)] hover:text-[var(--success)]"
                    >
                      {item.completed ? <CircleCheck size={14} /> : <Circle size={14} />}
                    </button>
                    <span
                      className={
                        item.completed
                          ? "text-xs text-[var(--muted-foreground)] line-through"
                          : "text-xs"
                      }
                    >
                      {item.text}
                    </span>
                  </li>
                ))}
              </ul>
              <form
                className="mt-1.5 flex gap-1.5"
                onSubmit={(event) => {
                  event.preventDefault();
                  const text = (itemText[checklist.id] ?? "").trim();
                  if (text) onAddItem(checklist.id, text);
                }}
              >
                <Input
                  className="h-7 text-xs"
                  placeholder="Add item"
                  aria-label={`Add item to ${checklist.title}`}
                  value={itemText[checklist.id] ?? ""}
                  onChange={(event) => onItemTextChange(checklist.id, event.target.value)}
                />
                <Button size="sm" variant="ghost" type="submit">
                  Add
                </Button>
              </form>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
