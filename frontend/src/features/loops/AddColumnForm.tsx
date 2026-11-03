import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** The slot after the last column: a button that opens a one-field form for a new column. */
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
  return (
    <div className="w-[260px] shrink-0">
      {adding ? (
        <form
          className="card-surface flex flex-col gap-2 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) return;
            onCreate(name.trim());
            onNameChange("");
            onAddingChange(false);
          }}
        >
          <Input
            autoFocus
            value={name}
            aria-label="New column name"
            placeholder="Column name"
            onChange={(event) => onNameChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                onAddingChange(false);
                onNameChange("");
              }
            }}
          />
          <div className="flex gap-1.5">
            <Button size="sm" type="submit" disabled={!name.trim()}>
              Add column
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onAddingChange(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <Button
          variant="secondary"
          className="w-full justify-start"
          onClick={() => onAddingChange(true)}
          disabled={readOnly}
        >
          <Plus size={14} /> Add column
        </Button>
      )}
    </div>
  );
}
