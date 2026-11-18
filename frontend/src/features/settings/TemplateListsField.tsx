import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { moveItem } from "@/lib/utils";

type Direction = "up" | "down";

/** The row's name in its buttons: the list's name, or its number while it has none. */
function rowName(entry: string, index: number): string {
  return entry.trim() || `list ${index + 1}`;
}

/** Keys for `count` new rows, after every key in `keys`. */
function freshKeys(keys: readonly number[], count: number): number[] {
  const start = keys.reduce((max, key) => Math.max(max, key + 1), 0);
  return Array.from({ length: count }, (_, offset) => start + offset);
}

/**
 * The template's list names in order, with move, remove and add. One empty entry always stays.
 * Each row keeps its own key while it moves, so its field keeps what it shows; a moved row keeps
 * the focus on its move button (the other one once it reached an end), and a screen reader hears
 * its new position (WCAG 2.4.3, 4.1.3).
 */
export function TemplateListsField({
  lists,
  onListsChange,
}: {
  lists: string[];
  onListsChange: Dispatch<SetStateAction<string[]>>;
}) {
  const announce = useAnnounce();
  const [keys, setKeys] = useState<number[]>(() => lists.map((_, index) => index));
  // The lists were replaced from outside (a template loaded): every row is new.
  if (keys.length !== lists.length) setKeys(freshKeys(keys, lists.length));
  const rows = useRef(new Map<number, HTMLElement>());
  const pendingFocus = useRef<{ key: number; direction: Direction } | null>(null);

  // After a move the row is where it moved to; its button takes the focus back.
  useEffect(() => {
    const pending = pendingFocus.current;
    if (!pending) return;
    pendingFocus.current = null;
    const row = rows.current.get(pending.key);
    const button = (direction: Direction) =>
      row?.querySelector<HTMLButtonElement>(`[data-move="${direction}"]`);
    const same = button(pending.direction);
    const target = same?.disabled ? button(pending.direction === "up" ? "down" : "up") : same;
    target?.focus();
  });

  function moveList(index: number, direction: Direction) {
    const target = direction === "up" ? index - 1 : index + 1;
    const key = keys[index];
    if (target < 0 || target >= lists.length || key === undefined) return;
    pendingFocus.current = { key, direction };
    setKeys((current) => moveItem(current, index, target));
    onListsChange((current) => moveItem(current, index, target));
    announce(
      `${rowName(lists[index] ?? "", index)} moved to position ${target + 1} of ${lists.length}.`,
    );
  }

  function removeList(index: number) {
    setKeys((current) =>
      current.length === 1 ? freshKeys(current, 1) : current.filter((_, at) => at !== index),
    );
    onListsChange((current) =>
      current.length === 1 ? [""] : current.filter((_, position) => position !== index),
    );
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Lists
      </legend>
      {lists.map((entry, index) => {
        const key = keys[index] ?? -1 - index;
        const name = rowName(entry, index);
        return (
          <div
            key={key}
            ref={(node) => {
              if (node) rows.current.set(key, node);
              else rows.current.delete(key);
            }}
            className="flex items-center gap-1.5"
          >
            <Input
              value={entry}
              aria-label={`List ${index + 1}`}
              placeholder={`List ${index + 1}`}
              onChange={(event) =>
                onListsChange((current) =>
                  current.map((value, position) =>
                    position === index ? event.target.value : value,
                  ),
                )
              }
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              data-move="up"
              aria-label={`Move ${name} up`}
              title="Move up"
              disabled={index === 0}
              onClick={() => moveList(index, "up")}
            >
              <ChevronUp size={14} aria-hidden="true" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              data-move="down"
              aria-label={`Move ${name} down`}
              title="Move down"
              disabled={index === lists.length - 1}
              onClick={() => moveList(index, "down")}
            >
              <ChevronDown size={14} aria-hidden="true" />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={`Remove ${name}`}
              title="Remove list"
              onClick={() => removeList(index)}
            >
              <Trash2 size={14} aria-hidden="true" />
            </Button>
          </div>
        );
      })}
      <div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => {
            setKeys((current) => [...current, ...freshKeys(current, 1)]);
            onListsChange((current) => [...current, ""]);
          }}
        >
          <Plus size={14} aria-hidden="true" /> Add list
        </Button>
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        Empty lists fall back to Backlog → Done when a board is created.
      </p>
    </fieldset>
  );
}
