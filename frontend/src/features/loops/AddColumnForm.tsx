import { Plus } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * The slot after the last column: a button that opens a one-field form for a new column. Once the
 * form closes (the column added, Cancel or Escape) the focus is back on "Add column" (WCAG 2.4.3).
 */
export function AddColumnForm({
  adding,
  onAddingChange,
  name,
  onNameChange,
  readOnly,
  onCreate,
}: {
  adding: boolean;
  onAddingChange: (adding: boolean) => void;
  name: string;
  onNameChange: (name: string) => void;
  readOnly: boolean;
  onCreate: (name: string) => void;
}) {
  const slot = useRef<HTMLDivElement>(null);
  const refocus = useRef(false);

  useEffect(() => {
    if (!refocus.current || adding) return;
    refocus.current = false;
    slot.current?.querySelector("button")?.focus();
  });

  function close() {
    refocus.current = true;
    onNameChange("");
    onAddingChange(false);
  }

  return (
    <div ref={slot} className="w-[240px] shrink-0">
      {adding ? (
        <form
          className="card-surface flex flex-col gap-2 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) return;
            onCreate(name.trim());
            close();
          }}
        >
          <Input
            autoFocus
            value={name}
            aria-label="New column name"
            placeholder="Column name"
            onChange={(event) => onNameChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") close();
            }}
          />
          <div className="flex gap-1.5">
            <Button size="sm" type="submit" disabled={!name.trim()}>
              Add column
            </Button>
            <Button size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <Button
          variant="quiet"
          className="w-full justify-start"
          onClick={() => onAddingChange(true)}
          disabled={readOnly}
        >
          <Plus size={14} aria-hidden="true" /> Add column
        </Button>
      )}
    </div>
  );
}
