import { useCallback, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnnouncerProvider } from "./announcer";
import { ToastItem } from "./toast-item";
import { ToastContext, withToast, type Toast, type ToastInput } from "./useToast";

/**
 * A live list of toasts: in the page from the first render, so a screen reader reads each toast
 * added to it. `aria-live` itself, because a Radix dialog keeps exactly the `[aria-live]` elements
 * readable while it hides the rest of the page.
 */
function ToastList({
  toasts,
  live,
  onDismiss,
}: {
  toasts: Toast[];
  live: "polite" | "assertive";
  onDismiss: (id: number) => void;
}) {
  return (
    <div aria-live={live} data-toasts={live} className="flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

/**
 * The toasts at the bottom right, and the announcer that comes with them, so every view under the
 * provider can also announce. An error is read at once and stays until it is dismissed; any other
 * toast is read after what the screen reader is reading and leaves by itself. At most three show,
 * and the same message again replaces the one shown (`withToast`).
 *
 * The toasts are drawn in the body, beside the app, not inside it. The app's root is a stacking
 * context of its own (`#root` in `index.css`) and a dialog is portalled to the body above it, so a
 * toast drawn inside the root sat under every dialog's backdrop, dimmed and blurred: a refusal
 * that came while a dialog was open could not be read. In the body `z-[60]` puts a toast over a
 * dialog (`z-50`) and its backdrop (`z-40`).
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const lastId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(({ title, description, variant = "info", action }: ToastInput) => {
    lastId.current += 1;
    const toast: Toast = { id: lastId.current, title, description, variant, action };
    setToasts((current) => withToast(current, toast));
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <AnnouncerProvider>
      <ToastContext.Provider value={value}>
        {children}
        {createPortal(
          <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(340px,90vw)] flex-col gap-2">
            <ToastList
              toasts={toasts.filter((toast) => toast.variant === "error")}
              live="assertive"
              onDismiss={dismiss}
            />
            <ToastList
              toasts={toasts.filter((toast) => toast.variant !== "error")}
              live="polite"
              onDismiss={dismiss}
            />
          </div>,
          document.body,
        )}
      </ToastContext.Provider>
    </AnnouncerProvider>
  );
}
