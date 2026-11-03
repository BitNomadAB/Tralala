import { LabelChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { renderMarkdown } from "@/lib/markdown";
import { PRIORITIES, type BoardList, type Label, type Priority } from "@/lib/types";

/** The card's editable fields, kept apart from the card until "Save changes". */
export interface CardDraft {
  title: string;
  description: string;
  priority: Priority;
  due: string;
  labels: string[];
}

/** Title, description, priority, due date, list and labels. The list moves the card at once. */
export function CardDialogForm({
  draft,
  onDraftChange,
  preview,
  onPreviewChange,
  lists,
  listId,
  onMove,
  labelOptions,
}: {
  draft: CardDraft;
  onDraftChange: (draft: CardDraft) => void;
  preview: boolean;
  onPreviewChange: (preview: boolean) => void;
  lists: BoardList[];
  listId: string;
  onMove: (listId: string) => void;
  labelOptions: Label[];
}) {
  return (
    <div className="grid gap-3 md:grid-cols-[1fr_200px]">
      <div className="flex flex-col gap-2">
        <Field label="Title" htmlFor="card-title">
          <Input
            id="card-title"
            value={draft.title}
            onChange={(event) => onDraftChange({ ...draft, title: event.target.value })}
          />
        </Field>
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            Description
          </span>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant={preview ? "ghost" : "secondary"}
              onClick={() => onPreviewChange(false)}
            >
              Edit
            </Button>
            <Button
              size="sm"
              variant={preview ? "secondary" : "ghost"}
              onClick={() => onPreviewChange(true)}
            >
              Preview
            </Button>
          </div>
        </div>
        {preview ? (
          <div className="prose-card min-h-24 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3">
            {renderMarkdown(draft.description) ?? (
              <span className="text-xs text-[var(--muted-foreground)]">No description</span>
            )}
          </div>
        ) : (
          <Textarea
            aria-label="Card description (Markdown)"
            value={draft.description}
            onChange={(event) => onDraftChange({ ...draft, description: event.target.value })}
            placeholder="Markdown supported"
          />
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Field label="Priority" htmlFor="card-priority">
          <Select
            id="card-priority"
            value={draft.priority}
            onChange={(event) =>
              onDraftChange({ ...draft, priority: event.target.value as Priority })
            }
          >
            {PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {priority}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Due date" htmlFor="card-due">
          <Input
            id="card-due"
            type="date"
            value={draft.due}
            onChange={(event) => onDraftChange({ ...draft, due: event.target.value })}
          />
        </Field>
        <Field label="List" htmlFor="card-list">
          <Select id="card-list" value={listId} onChange={(event) => onMove(event.target.value)}>
            {lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            Labels
          </span>
          <div className="flex flex-wrap gap-1.5">
            {labelOptions.length === 0 ? (
              <span className="text-xs text-[var(--muted-foreground)]">
                No labels on this board yet.
              </span>
            ) : (
              labelOptions.map((label) => {
                const selected = draft.labels.includes(label.id);
                return (
                  <button
                    key={label.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() =>
                      onDraftChange({
                        ...draft,
                        labels: selected
                          ? draft.labels.filter((id) => id !== label.id)
                          : [...draft.labels, label.id],
                      })
                    }
                    className={selected ? "opacity-100" : "opacity-45"}
                  >
                    <LabelChip name={label.name} color={label.color} />
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
