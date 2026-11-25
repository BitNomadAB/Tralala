import { useCallback, useState } from "react";
import type { LoopDialog } from "./LoopDialogs";
import type { LoopView } from "./useLoopView";

/**
 * The one open dialog of the Loop's header. A link opens the completion dialog
 * (`?dialog=completion`, from a decision link) when the Loop offers it (`offered`, as "Loop
 * actions" does: not a draft, not read-only), and the address changed to it later opens it again;
 * a link the Loop does not offer opens nothing. The dialog only opens: the decision in it stays the
 * person's. Closing any dialog takes `dialog` out of the address, replacing the entry, so a reload
 * or Back does not open it again (as `useTicketDialog` drops `card`).
 */
export function useLoopDialog(view: Pick<LoopView, "dialog" | "closeDialog">, offered: boolean) {
  const linked: LoopDialog | null = view.dialog === "completion" && offered ? "completion" : null;
  const [open, setOpen] = useState<LoopDialog | null>(linked);
  const [seen, setSeen] = useState(view.dialog);
  if (view.dialog !== seen) {
    setSeen(view.dialog);
    if (linked !== null) setOpen(linked);
  }

  const { closeDialog } = view;
  const close = useCallback(() => {
    setOpen(null);
    closeDialog();
  }, [closeDialog]);

  return { open, setOpen, close };
}
