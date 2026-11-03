import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";

/** Saves the Loop's column names and the board's labels as a board template. */
export function SaveTemplateDialog({
  open,
  onOpenChange,
  name,
  onNameChange,
  description,
  onDescriptionChange,
  columnCount,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  onNameChange: (name: string) => void;
  description: string;
  onDescriptionChange: (description: string) => void;
  columnCount: number;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Save as template"
        description="Stores this Loop's column names and the board's labels for future Loops."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) onSave();
          }}
        >
          <Field label="Template name" htmlFor="loop-template-name">
            <Input
              id="loop-template-name"
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              required
              autoFocus
              maxLength={200}
            />
          </Field>
          <Field label="Description" htmlFor="loop-template-description">
            <Textarea
              id="loop-template-description"
              value={description}
              onChange={(event) => onDescriptionChange(event.target.value)}
              maxLength={20000}
            />
          </Field>
          <p className="text-[11px] text-[var(--muted-foreground)]">
            Captures {columnCount} columns. Tickets are not copied.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || saving}>
              {saving ? "Saving…" : "Save template"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
