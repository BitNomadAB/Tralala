import { createContext, useContext } from "react";

export type ToastVariant = "info" | "success" | "warning" | "error";

/** What a caller passes; an undefined description is the same as none. */
export interface ToastInput {
  title: string;
  description?: string | undefined;
  variant?: ToastVariant;
}

export interface ToastContextValue {
  push: (toast: ToastInput) => void;
}

/** Shared by `ToastProvider` (toast.tsx) and `useToast`; a component file exports only components. */
export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
