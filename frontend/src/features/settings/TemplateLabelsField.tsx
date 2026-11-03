import { Plus, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface LabelDraft {
  name: string;
  color: string;
}

const NEW_LABEL_COLOR = "#64748b";

/** The template's labels: a name and a colour each, with remove and add. */
export function TemplateLabelsField({
  labels,
  onLabelsChange,
}: {
  labels: LabelDraft[];
  onLabelsChange: Dispatch<SetStateAction<LabelDraft[]>>;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        Labels
      </legend>
      {labels.map((label, index) => (
        <div key={index} className="flex items-center gap-1.5">
          <Input
            value={label.name}
            aria-label={`Label ${index + 1} name`}
            placeholder="Label name"
            onChange={(event) =>
              onLabelsChange((current) =>
                current.map((value, position) =>
                  position === index ? { ...value, name: event.target.value } : value,
                ),
              )
            }
          />
          <input
            type="color"
            aria-label={`Label ${index + 1} color`}
            value={label.color}
            onChange={(event) =>
              onLabelsChange((current) =>
                current.map((value, position) =>
                  position === index ? { ...value, color: event.target.value } : value,
                ),
              )
            }
            className="h-9 w-12 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)]"
          />
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={`Remove label ${index + 1}`}
            title="Remove label"
            onClick={() =>
              onLabelsChange((current) => current.filter((_, position) => position !== index))
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
          onClick={() =>
            onLabelsChange((current) => [...current, { name: "", color: NEW_LABEL_COLOR }])
          }
        >
          <Plus size={14} /> Add label
        </Button>
      </div>
    </fieldset>
  );
}
