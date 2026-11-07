import { LabelChip } from "@/components/ui/badge";
import { Field, Input, Select } from "@/components/ui/input";
import { MarkdownField } from "@/components/ui/markdown-field";
import type { MarkdownOptions } from "@/lib/markdown";
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
  ticketHref,
}: {
  draft: CardDraft;
  onDraftChange: (draft: CardDraft) => void;
  /** Whether the description shows its Preview tab rather than Write. */
  preview: boolean;
  onPreviewChange: (preview: boolean) => void;
  lists: BoardList[];
  listId: string;
  onMove: (listId: string) => void;
  labelOptions: Label[];
  /** Links a Ticket key in the description to that Ticket; absent, keys stay text. */
  ticketHref?: MarkdownOptions["ticketHref"];
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
        <MarkdownField
          id="card-description"
          title="Description"
          label="Card description (Markdown)"
          value={draft.description}
          onChange={(description) => onDraftChange({ ...draft, description })}
          preview={preview}
          onPreviewChange={onPreviewChange}
          placeholder="Markdown supported"
          ticketHref={ticketHref}
        />
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
