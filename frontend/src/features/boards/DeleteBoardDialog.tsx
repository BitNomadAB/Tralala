import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import type { Board } from "@/lib/types";

/** Deletes an archived board for good once its name is typed back. */
export function DeleteBoardDialog({
  board,
  confirmName,
  onConfirmNameChange,
  deleting,
  onDelete,
  onClose,
}: {
  board: Board | null;
  confirmName: string;
  onConfirmNameChange: (name: string) => void;
  deleting: boolean;
  onDelete: (board: Board) => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={Boolean(board)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title="Delete board permanently"
        description="This deletes the board database and its backups. It cannot be undone."
      >
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (board) onDelete(board);
          }}
        >
          <Field label={`Type "${board?.name ?? ""}" to confirm`} htmlFor="confirm-name">
            <Input
              id="confirm-name"
              value={confirmName}
              onChange={(event) => onConfirmNameChange(event.target.value)}
              autoFocus
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="danger"
              type="submit"
              disabled={confirmName !== board?.name || deleting}
            >
              Delete board
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
