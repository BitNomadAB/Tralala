import { createContext, useContext } from "react";

export type ToastVariant = "info" | "success" | "warning" | "error";

export interface ToastContextValue {
  push: (toast: { title: string; description?: string; variant?: ToastVariant }) => void;
}

/** Shared by `ToastProvider` (toast.tsx) and `useToast`; a component file exports only components. */
export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
