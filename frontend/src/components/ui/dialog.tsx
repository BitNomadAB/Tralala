import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  children,
  className,
  title,
  description,
}: {
  children: ReactNode;
  className?: string;
  title: string;
  description?: string | undefined;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(680px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl scrollbar-thin",
          className,
        )}
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-base font-semibold text-[var(--foreground)]">
              {title}
            </DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                {description}
              </DialogPrimitive.Description>
            ) : null}
          </div>
          <DialogPrimitive.Close
            aria-label="Close dialog"
            className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
          >
            <X size={16} />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export const DialogTitle = DialogPrimitive.Title;

/**
 * A dialog that draws its own head: the overlay and the panel, nothing inside. The content names
 * the dialog with a `DialogTitle`. Escape closes it, except while the focus sits in something that
 * takes Escape itself (an open listbox, or an element marked `data-keeps-escape`, such as a field
 * being edited inline): Radix listens on the document before the field sees the key, so without
 * this one Escape would close the menu and the whole dialog at once.
 */
export function DialogFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" />
      <DialogPrimitive.Content
        aria-describedby={undefined}
        onEscapeKeyDown={(event) => {
          if (keepsEscape(event.target)) event.preventDefault();
        }}
        className={cn(
          "fixed z-50 overflow-hidden border border-[var(--border)] bg-[var(--background)] shadow-2xl",
          className,
        )}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/** Whether a key press on `target` belongs to an open listbox or a field that handles Escape. */
function keepsEscape(target: EventTarget | null): boolean {
  return (
    target instanceof Element && target.closest('[role="listbox"], [data-keeps-escape]') !== null
  );
}
