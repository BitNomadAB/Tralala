import { useCallback, useMemo, useRef, useState } from "react";
import { AnnouncerProvider } from "./announcer";
import { ToastItem } from "./toast-item";
import { ToastContext, type Toast, type ToastInput } from "./useToast";

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
 * toast is read after what the screen reader is reading and leaves by itself.
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
    setToasts((current) => [...current, toast]);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <AnnouncerProvider>
      <ToastContext.Provider value={value}>
        {children}
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
        </div>
      </ToastContext.Provider>
    </AnnouncerProvider>
  );
}
