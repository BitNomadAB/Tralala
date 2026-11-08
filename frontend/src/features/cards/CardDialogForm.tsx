import { Button } from "@/components/ui/button";
import { MarkdownField } from "@/components/ui/markdown-field";
import type { MarkdownOptions } from "@/lib/markdown";

/**
 * The description with Write/Preview and its Save button, which is pressable once the text
 * differs from what is saved. The title, priority, due date, column and labels are edited in the
 * Ticket's head and rail, each saving itself.
 */
export function CardDialogForm({
  description,
  onDescriptionChange,
  preview,
  onPreviewChange,
  dirty,
  saving,
  onSave,
  readOnly = false,
  ticketHref,
}: {
  description: string;
  onDescriptionChange: (description: string) => void;
  /** Whether the description shows its Preview tab rather than Write. */
  preview: boolean;
  onPreviewChange: (preview: boolean) => void;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  readOnly?: boolean | undefined;
  /** Links a Ticket key in the description to that Ticket; absent, keys stay text. */
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  return (
    <div className="flex flex-col gap-2">
      <MarkdownField
        id="card-description"
        title="Description"
        label="Card description (Markdown)"
        value={description}
        onChange={onDescriptionChange}
        preview={preview}
        onPreviewChange={onPreviewChange}
        placeholder="Markdown supported"
        ticketHref={ticketHref}
      />
      {readOnly ? null : (
        <div>
          <Button variant="secondary" size="sm" onClick={onSave} disabled={!dirty || saving}>
            {saving ? "Saving…" : "Save description"}
          </Button>
        </div>
      )}
    </div>
  );
}
