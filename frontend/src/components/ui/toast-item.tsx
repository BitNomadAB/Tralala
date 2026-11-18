import { CheckCircle2, Info, TriangleAlert, X, XCircle } from "lucide-react";
import { useCallback, type PointerEvent } from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";
import { TOAST_DURATION_MS, toastExpires, type Toast, type ToastVariant } from "./useToast";
import { useToastTimer } from "./useToastTimer";

const icons = {
  info: Info,
  success: CheckCircle2,
  warning: TriangleAlert,
  error: XCircle,
} as const;

const tones: Record<ToastVariant, string> = {
  info: "text-[var(--primary)]",
  success: "text-[var(--success)]",
  warning: "text-[var(--warning)]",
  error: "text-[var(--destructive)]",
};

/**
 * A Radix dialog closes on a pointer press outside it, which a toast over the dialog is. Kept from
 * the document, the press dismisses the toast and leaves the dialog open.
 */
const keepPressFromDialogs = {
  onPointerDown: (event: PointerEvent<HTMLElement>) => {
    event.stopPropagation();
  },
};

/**
 * One toast: its text, its action if it has one, and Dismiss. Its timer stands still while the
 * pointer is on it or focus is in it. An error has none, and neither has a toast with an action:
 * Undo may be the only way back, and a keyboard user reaches it only after the whole page, so it
 * stays until it is used or dismissed (WCAG 2.2.1); the provider keeps such toasts from piling up.
 */
export function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const { id, action } = toast;
  const dismiss = useCallback(() => {
    onDismiss(id);
  }, [onDismiss, id]);
  const timer = useToastTimer(toastExpires(toast) ? TOAST_DURATION_MS : null, dismiss);
  const Icon = icons[toast.variant];

  return (
    <div
      data-toast={toast.variant}
      className="pointer-events-auto flex items-start gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 shadow-lg"
      {...timer.handlers}
      {...keepPressFromDialogs}
    >
      <Icon size={16} aria-hidden="true" className={cn("mt-0.5 shrink-0", tones[toast.variant])} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--foreground)]">{toast.title}</p>
        {toast.description ? (
          <p className="mt-0.5 text-xs text-[var(--muted-foreground)] break-words">
            {toast.description}
          </p>
        ) : null}
        {action ? (
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => {
              action.onClick();
              dismiss();
            }}
          >
            {action.label}
          </Button>
        ) : null}
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Dismiss notification"
        className="-my-1 -mr-1 shrink-0"
        onClick={dismiss}
      >
        <X size={14} aria-hidden="true" />
      </Button>
    </div>
  );
}
