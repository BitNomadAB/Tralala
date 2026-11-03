import { CheckCircle2, Info, TriangleAlert, XCircle } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { ToastContext, type ToastInput, type ToastVariant } from "./useToast";

interface Toast {
  id: number;
  title: string;
  description: string | undefined;
  variant: ToastVariant;
}

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

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback(
    ({ title, description, variant = "info" }: ToastInput) => {
      const id = Date.now() + Math.random();
      setToasts((current) => [...current, { id, title, description, variant }]);
      window.setTimeout(() => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
      }, 5000);
    },
    [],
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(340px,90vw)] flex-col gap-2"
      >
        {toasts.map((toast) => {
          const Icon = icons[toast.variant];
          return (
            <div
              key={toast.id}
              role="status"
              className="pointer-events-auto flex gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 shadow-lg"
            >
              <Icon size={16} className={cn("mt-0.5 shrink-0", tones[toast.variant])} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-[var(--foreground)]">{toast.title}</p>
                {toast.description ? (
                  <p className="mt-0.5 text-xs text-[var(--muted-foreground)] break-words">
                    {toast.description}
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
