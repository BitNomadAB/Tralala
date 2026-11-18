import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ReasonButton } from "@/components/ui/reason-button";

/** A question before an action: what is asked, what happens, and the name of the action. */
export interface Confirmation {
  title: string;
  consequence: string;
  confirmLabel: string;
}

/**
 * Asks before an action that cannot be undone (WCAG 3.3.4). The title asks the question, the
 * description says what happens, and the confirm button names the action. Focus starts on Cancel,
 * the choice that changes nothing, so an Enter pressed out of habit does not confirm. The caller
 * closes it: at once in `onConfirm` when the button that opened it stays and says that the action
 * is under way, or once the action is done when that button goes with it (a removal), with `busy`
 * saying what it waits for meanwhile and `onCloseAutoFocus` sending focus on.
 */
export function ConfirmDialog({
  question,
  busy = null,
  onConfirm,
  onCancel,
  onCloseAutoFocus,
}: {
  /** What to ask; the dialog is open while there is a question. */
  question: Confirmation | null;
  /** While the confirmed action runs with the dialog open: what it waits for ("Removing…"). */
  busy?: string | null | undefined;
  onConfirm: () => void;
  onCancel: () => void;
  onCloseAutoFocus?: ((event: Event) => void) | undefined;
}) {
  const cancelId = useId();
  return (
    <Dialog open={question !== null} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent
        title={question?.title ?? ""}
        description={question?.consequence}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          document.getElementById(cancelId)?.focus();
        }}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <div className="mt-2 flex justify-end gap-2">
          <Button id={cancelId} variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <ReasonButton variant="danger" disabledReason={busy} onClick={onConfirm}>
            {question?.confirmLabel}
          </ReasonButton>
        </div>
      </DialogContent>
    </Dialog>
  );
}
