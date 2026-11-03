import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { moveItem } from "@/lib/utils";

/** The template's list names in order, with move, remove and add. One empty entry always stays. */
export function TemplateListsField({
  lists,
  onListsChange,
}: {
  lists: string[];
  onListsChange: Dispatch<SetStateAction<string[]>>;
}) {
  const moveList = (index: number, offset: number) => {
    onListsChange((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      return moveItem(current, index, target);
    });
  };

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Lists
      </legend>
      {lists.map((entry, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <Input
            value={entry}
            aria-label={`List ${index + 1}`}
            placeholder={`List ${index + 1}`}
            onChange={(event) =>
              onListsChange((current) =>
                current.map((value, position) => (position === index ? event.target.value : value)),
              )
            }
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Move list ${index + 1} up`}
            title="Move up"
            disabled={index === 0}
            onClick={() => moveList(index, -1)}
          >
            <ChevronUp size={14} />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Move list ${index + 1} down`}
            title="Move down"
            disabled={index === lists.length - 1}
            onClick={() => moveList(index, 1)}
          >
            <ChevronDown size={14} />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Remove list ${index + 1}`}
            title="Remove list"
            onClick={() =>
              onListsChange((current) =>
                current.length === 1 ? [""] : current.filter((_, position) => position !== index),
              )
            }
          >
            <Trash2 size={14} />
          </Button>
        </div>
      ))}
      <div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => onListsChange((current) => [...current, ""])}
        >
          <Plus size={14} /> Add list
        </Button>
      </div>
      <p className="text-xs text-[var(--muted-foreground)]">
        Empty lists fall back to Backlog → Done when a board is created.
      </p>
    </fieldset>
  );
}
