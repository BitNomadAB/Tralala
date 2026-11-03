import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { AgentPicker } from "@/features/boards/AgentPicker";
import { RepositoryPicker } from "@/features/boards/RepositoryPicker";

/** The board's editable settings while the edit dialog is open. */
export interface BoardEditDraft {
  name: string;
  description: string;
  repositoryIds: string[];
  agentIds: string[];
}

export function EditBoardDialog({
  open,
  onOpenChange,
  draft,
  onDraftChange,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: BoardEditDraft;
  onDraftChange: (draft: BoardEditDraft) => void;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Edit board"
        description="Name, description, and the code and agents this board is about."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.name.trim()) onSave();
          }}
        >
          <Field label="Name" htmlFor="board-edit-name">
            <Input
              id="board-edit-name"
              value={draft.name}
              onChange={(event) => onDraftChange({ ...draft, name: event.target.value })}
              required
              maxLength={200}
            />
          </Field>
          <Field label="Description" htmlFor="board-edit-description">
            <Textarea
              id="board-edit-description"
              value={draft.description}
              onChange={(event) => onDraftChange({ ...draft, description: event.target.value })}
              maxLength={20000}
            />
          </Field>
          <RepositoryPicker
            selected={draft.repositoryIds}
            onChange={(repositoryIds) => onDraftChange({ ...draft, repositoryIds })}
            disabled={saving}
          />
          <AgentPicker
            selected={draft.agentIds}
            onChange={(agentIds) => onDraftChange({ ...draft, agentIds })}
            disabled={saving}
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !draft.name.trim()}>
              {saving ? "Saving?" : "Save board"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
